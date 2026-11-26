import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MemorySearchPreviewTool
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceNotFoundError, TooManyRedirectsError
from requests import Response

from agentops.contracts import LabError, canonical
from agentops.delivery_memory import MemoryDelivery, NativeMemory
from test_delivery_native import Journal

OID = "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-0000-0000-0000-bbbbbbbbbbbb"


def model(value):
    return SimpleNamespace(as_dict=lambda: value)


class NativeMemoryTests(unittest.TestCase):
    def memory(self, store="contoso-memory-v1"):
        client = Mock()
        memory = NativeMemory(client, "prompt", store, OID, {OID, OTHER}, lambda: None)
        client.beta.memory_stores.list_memories.return_value = []
        return memory, client.beta.memory_stores

    def test_sdk_serialization_sets_ttl_and_disables_unwanted_memory_types(self):
        memory, api = self.memory()
        desired = NativeMemory.definition()
        api.get.side_effect = [ResourceNotFoundError("missing"), model({"definition": desired})]
        memory.ensure_store()
        actual = api.create.call_args.kwargs["definition"].as_dict()
        self.assertEqual(actual["options"]["default_ttl_seconds"], 86400)
        self.assertFalse(actual["options"]["procedural_memory_enabled"])
        self.assertFalse(actual["options"]["chat_summary_enabled"])
        self.assertEqual(MemorySearchPreviewTool(memory.prompt_tool()).as_dict(), memory.prompt_tool())
        api.get.side_effect = [model({"definition": {**desired, "chat_model": "another-model"}})]
        with self.assertRaisesRegex(LabError, "policy drift"):
            memory.ensure_store()
        self.assertEqual(api.create.call_count, 1)

    def test_harness_foreign_callers_and_cross_scope_results_fail_closed(self):
        with self.assertRaisesRegex(LabError, "Harness memory"):
            NativeMemory(Mock(), "harness", "contoso-memory-v1", OID, {OID}, lambda: None)
        with self.assertRaisesRegex(LabError, "outside"):
            NativeMemory(Mock(), "hosted", "contoso-memory-v1", OTHER, {OID}, lambda: None)
        memory, api = self.memory()
        api.list_memories.return_value = [model({"scope": OTHER, "memory_id": "memory-1"})]
        with self.assertRaisesRegex(LabError, "crossed"):
            memory.snapshot()
        api.search_memories.return_value = model({"usage": {}, "memories": [{"memory_item": {"scope": OTHER}}]})
        with self.assertRaisesRegex(LabError, "crossed"):
            memory.recall()

    def test_incomplete_async_update_is_not_success_or_replayed(self):
        memory, api = self.memory()
        poller = api.begin_update_memories.return_value
        poller.update_id = "update-1"
        poller.done.return_value = False
        with self.assertRaisesRegex(LabError, "five minutes"):
            memory.learn_fixture(Mock())
        poller.result.assert_called_once_with(timeout=300)
        api.begin_update_memories.assert_called_once()
        self.assertEqual(api.begin_update_memories.call_args.kwargs["scope"], OID)

    def test_native_learning_uses_raw_status_usage_and_message_type(self):
        memory, api = self.memory()
        item = {"scope": OID, "memory_id": "memory-1", "content": "Synthetic preference"}
        api.list_memories.side_effect = [[], [model(item)]]
        result = {"status": "completed", "update_id": "update-1",
                  "result": {"memory_operations": [{"kind": "create", "memory_item": item}],
                             "usage": {"embedding_tokens": 2, "input_tokens": 10, "output_tokens": 3, "total_tokens": 15}}}
        poller = api.begin_update_memories.return_value
        poller.done.return_value = True
        poller.result.return_value = result
        poller.update_id = "update-1"
        journal = Mock()
        measured = memory.learn_fixture(journal)
        self.assertEqual(measured["usage"], result["result"]["usage"])
        args = api.begin_update_memories.call_args.kwargs
        self.assertEqual(args["items"][0]["type"], "message")
        raw = SimpleNamespace(http_response=SimpleNamespace(json=lambda: {"status": "failed"}))
        self.assertEqual(args["cls"](raw, model({"usage": {"input_tokens": 0}}), {}), {"status": "failed"})
        self.assertEqual(journal.call_args_list[1].args[0]["update_id"], "update-1")
        self.assertNotIn("continuation", str(measured))

    def test_completion_from_another_operation_is_rejected(self):
        memory, api = self.memory()
        poller = api.begin_update_memories.return_value
        poller.update_id, poller.done.return_value = "update-1", True
        poller.result.return_value = {"update_id": "another-update", "status": "completed"}
        with self.assertRaisesRegex(LabError, "another operation"):
            memory.learn_fixture(Mock())

    def test_status_reconciliation_is_authenticated_get_not_a_replayed_extraction(self):
        memory, api = self.memory()
        response = memory.project.send_request.return_value
        response.status_code = 200
        response.json.return_value = {"update_id": "update-1", "status": "in_progress"}
        self.assertEqual(memory.read_update("update-1")["status"], "in_progress")
        request = memory.project.send_request.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.url, "{endpoint}/memory_stores/contoso-memory-v1/updates/update-1?api-version=v1")
        response.close.assert_called_once()
        api.begin_update_memories.assert_not_called()
        with self.assertRaisesRegex(LabError, "Invalid native update"):
            memory.read_update("../another-scope")

    def test_real_sdk_routes_status_read_and_refuses_redirect(self):
        response = Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response.raw = Mock()
        response._content = canonical({"update_id": "update-1", "status": "in_progress"})
        response._content_consumed = True
        credential = SimpleNamespace(get_token=lambda *args, **kwargs: AccessToken("offline-test-token", 9999999999))
        endpoint = "https://unit.services.ai.azure.com/api/projects/lab"
        with AIProjectClient(endpoint, credential, allow_preview=True) as client, \
                patch("requests.Session.request", return_value=response) as wire:
            memory = NativeMemory(client, "prompt", "contoso-memory-v1", OID, {OID}, lambda: None)
            self.assertEqual(memory.read_update("update-1")["status"], "in_progress")
            self.assertEqual(wire.call_args.args[1],
                             endpoint + "/memory_stores/contoso-memory-v1/updates/update-1?api-version=v1")
            self.assertEqual(wire.call_args.kwargs["headers"]["Authorization"], "Bearer offline-test-token")
            self.assertEqual(wire.call_args.kwargs["headers"]["Foundry-Features"], "MemoryStores=V1Preview")
            response.status_code = 302
            response.headers["Location"] = "https://foreign.invalid/"
            wire.reset_mock()
            with self.assertRaises(TooManyRedirectsError):
                memory.read_update("update-1")
            self.assertEqual(wire.call_count, 1)

    def test_pending_extraction_blocks_replay_and_deletion_until_reconciled(self):
        memory, api = self.memory()
        journal = Journal()
        workflow = MemoryDelivery(memory, journal, "dev")
        poller = api.begin_update_memories.return_value
        poller.update_id, poller.done.return_value = "update-1", False
        with self.assertRaisesRegex(LabError, "five minutes"):
            workflow.learn()
        for action in (workflow.learn, workflow.forget):
            with self.assertRaisesRegex(LabError, "Pending"):
                action()
        self.assertEqual(api.begin_update_memories.call_count, 1)
        api.delete_scope.assert_not_called()
        response = memory.project.send_request.return_value
        response.status_code = 200
        response.json.return_value = {"update_id": "update-1", "status": "failed", "error": {"code": "test-failure"}}
        self.assertEqual(workflow.reconcile()["status"], "failed")
        api.delete_scope.return_value = model({"deleted": True, "scope": OID, "name": memory.store})
        self.assertEqual(workflow.forget()["status"], "forgotten")
        self.assertEqual(api.begin_update_memories.call_count, 1)

    def test_uncertain_deletion_blocks_new_writes(self):
        memory, api = self.memory()
        workflow = MemoryDelivery(memory, Journal(), "dev")
        api.delete_scope.side_effect = TimeoutError("unknown deletion outcome")
        with self.assertRaises(TimeoutError):
            workflow.forget()
        with self.assertRaisesRegex(LabError, "Pending"):
            workflow.learn()
        with self.assertRaisesRegex(LabError, "quiescence"):
            workflow.reconcile()
        api.begin_update_memories.assert_not_called()

    def test_nonempty_ttl_migration_is_explicitly_blocked_without_copying(self):
        memory, api = self.memory()
        target, target_api = self.memory("contoso-memory-v2")
        api.list_memories.return_value = [model({
            "memory_id": "memory-1", "scope": OID, "content": "Synthetic preference",
            "updated_at": "2026-01-01T00:00:00Z", "kind": "user_profile"})]
        plan = memory.migration_plan(target)
        self.assertFalse(plan["copy_allowed"])
        self.assertFalse(plan["empty_scope_cutover_allowed"])
        self.assertTrue(plan["blocking"])
        target_api.create_memory.assert_not_called()
        self.assertNotIn("records", plan)
        self.assertNotIn("content", str(plan))

    def test_delete_requires_service_confirmation_and_empty_readback(self):
        memory, api = self.memory()
        api.delete_scope.return_value = model({"deleted": True, "scope": OID, "name": memory.store})
        self.assertTrue(memory.forget()["deleted"])
        api.delete_scope.assert_called_once_with(memory.store, scope=OID, headers={"Foundry-Features": "MemoryStores=V1Preview"})
        api.delete_scope.return_value = model({"deleted": False, "scope": OID, "name": memory.store})
        with self.assertRaisesRegex(LabError, "not confirmed"):
            memory.forget()
