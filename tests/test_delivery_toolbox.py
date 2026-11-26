import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from azure.ai.projects import AIProjectClient
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceNotFoundError
from requests import Response

from agentops.contracts import LabError, canonical, parse_json
from agentops.delivery_contracts import TOOL_NAME
from agentops.delivery_knowledge import MCP_API
from agentops.delivery_toolbox import NativeToolbox, ToolboxDelivery
from test_delivery_native import Journal, model


PROJECT = "https://unit.services.ai.azure.com/api/projects/lab"
ACCOUNT = ("/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/unit"
           "/providers/Microsoft.CognitiveServices/accounts/unit")
POLICY = ACCOUNT + "/raiPolicies/Microsoft.DefaultV2"
TARGET = {"project_endpoint": PROJECT, "project_resource_id": ACCOUNT + "/projects/lab",
          "search_endpoint": "https://unit.search.windows.net",
          "tool_mcp_url": "https://unit.azurecontainerapps.io/mcp"}


def tools(digest):
    return [{"type": "mcp", "server_label": label, "server_url": url,
             "allowed_tools": [tool_name], "require_approval": "never",
             "project_connection_id": f"{label}-{digest[:20]}"}
            for label, url, tool_name in (
                ("knowledge-base", TARGET["search_endpoint"] + "/knowledgebases/kb-" + "c" * 20
                 + "/mcp?api-version=" + MCP_API, "knowledge_base_retrieve"),
                ("lab-tools", TARGET["tool_mcp_url"] + "/releases/" + digest, TOOL_NAME))]


class ToolboxFixture:
    def __init__(self):
        self.versions, self.defaults = {}, {}
        self.foundry = Mock(target=TARGET)
        self.api = self.foundry.client.toolboxes
        self.api.get.side_effect = self.get
        self.api.create_version.side_effect = self.create
        self.api.list_versions.side_effect = lambda name, **kwargs: [
            model(item) for item in self.versions[name].values()]
        self.api.get_version.side_effect = lambda name, version: model(self.versions[name][version])
        self.toolbox = NativeToolbox(self.foundry, lambda: None)

    def get(self, name):
        if name not in self.versions:
            raise ResourceNotFoundError("Synthetic toolbox not found")
        return model({"name": name, "default_version": self.defaults[name]})

    def create(self, name, body):
        versions = self.versions.setdefault(name, {})
        version = str(len(versions) + 1)
        versions[version] = {"name": name, "version": version, **copy.deepcopy(body)}
        self.defaults.setdefault(name, version)
        return model(versions[version])


class ToolboxTests(unittest.TestCase):
    def test_release_local_creation_is_idempotent_and_preserves_retained_toolbox(self):
        world, journal = ToolboxFixture(), Journal()
        workflow = ToolboxDelivery(world.toolbox, journal, "dev")
        first = workflow.ensure("a" * 64, tools("a" * 64), POLICY)
        self.assertEqual(workflow.ensure("a" * 64, tools("a" * 64), POLICY), first)
        second = workflow.ensure("b" * 64, tools("b" * 64), POLICY)
        self.assertNotEqual(first["name"], second["name"])
        world.toolbox.verify("a" * 64, tools("a" * 64), POLICY, first)
        self.assertIn("/versions/1/mcp?api-version=v1", first["mcp_endpoint"])
        self.assertEqual(world.api.create_version.call_count, 2)
        world.api.update.assert_not_called()
        world.api.delete_version.assert_not_called()

    def test_uncertain_creation_blocks_retry_and_reconciles_without_resubmitting(self):
        world, journal = ToolboxFixture(), Journal()
        workflow = ToolboxDelivery(world.toolbox, journal, "dev")
        def create_then_timeout(name, body):
            world.create(name, body)
            raise TimeoutError("Lost creation response")
        world.api.create_version.side_effect = create_then_timeout
        with self.assertRaises(TimeoutError):
            workflow.ensure("a" * 64, tools("a" * 64), POLICY)
        self.assertEqual(journal.saved[0]["toolboxes"]["dev"]["a" * 64]["status"], "started")
        with self.assertRaisesRegex(LabError, "Pending toolbox"):
            workflow.ensure("a" * 64, tools("a" * 64), POLICY)
        receipt = workflow.reconcile("a" * 64, tools("a" * 64), POLICY)
        self.assertEqual(receipt["version"], "1")
        self.assertEqual(workflow.ensure("a" * 64, tools("a" * 64), POLICY), receipt)
        world.api.create_version.assert_called_once()

    def test_missing_or_changed_pending_intent_cannot_be_repaired_by_creation(self):
        world, journal = ToolboxFixture(), Journal()
        workflow = ToolboxDelivery(world.toolbox, journal, "dev")
        world.api.create_version.side_effect = TimeoutError("Unknown request outcome")
        with self.assertRaises(TimeoutError):
            workflow.ensure("a" * 64, tools("a" * 64), POLICY)
        world.api.list_versions.side_effect = ResourceNotFoundError("Still absent")
        with self.assertRaises(ResourceNotFoundError):
            workflow.reconcile("a" * 64, tools("a" * 64), POLICY)
        changed = tools("a" * 64)
        changed[0]["server_url"] = changed[0]["server_url"].replace("c" * 20, "d" * 20)
        with self.assertRaisesRegex(LabError, "intent changed"):
            workflow.reconcile("a" * 64, changed, POLICY)
        world.api.create_version.assert_called_once()

    def test_default_drift_moves_unpinned_resolution_but_not_retained_reference(self):
        world = ToolboxFixture()
        digest = "a" * 64
        receipt = world.toolbox.ensure(digest, tools(digest), POLICY)
        before = world.toolbox.inspect_reference(digest)
        body = world.toolbox.desired(digest, tools(digest), POLICY)
        body["tools"][1]["require_approval"] = "always"
        world.create(receipt["name"], body)
        world.defaults[receipt["name"]] = "2"
        unpinned = world.toolbox.inspect_reference(digest)
        pinned = world.toolbox.inspect_reference(digest, receipt["version"])
        self.assertEqual((before["version"], unpinned["version"], pinned["version"]), ("1", "2", "1"))
        self.assertEqual(before["definition_digest"], pinned["definition_digest"])
        self.assertNotEqual(before["definition_digest"], unpinned["definition_digest"])
        self.assertFalse(unpinned["runtime_invocation_verified"])
        with self.assertRaisesRegex(LabError, "multiple versions"):
            world.toolbox.verify(digest, tools(digest), POLICY, receipt)
        world.api.update.assert_not_called()

    def test_hidden_capability_policy_or_binding_drift_is_rejected(self):
        for mutation in ("header", "skills", "policy", "endpoint", "default"):
            world = ToolboxFixture()
            digest = "a" * 64
            receipt = world.toolbox.ensure(digest, tools(digest), POLICY)
            actual = world.versions[receipt["name"]]["1"]
            if mutation == "header":
                actual["tools"][1]["headers"] = {"x-unreviewed": "synthetic"}
            elif mutation == "skills":
                actual["skills"] = [{"type": "skill_reference", "name": "unreviewed"}]
            elif mutation == "policy":
                actual["policies"]["rai_config"]["unreviewed"] = True
            elif mutation == "endpoint":
                receipt["mcp_endpoint"] = PROJECT + "/toolboxes/shared/mcp?api-version=v1"
            else:
                world.defaults[receipt["name"]] = "latest"
            with self.subTest(mutation=mutation), self.assertRaises(LabError):
                world.toolbox.verify(digest, tools(digest), POLICY, receipt)

    def test_lease_loss_refuses_creation_and_unreviewed_auth_never_reaches_service(self):
        world = ToolboxFixture()
        world.toolbox.check_write = Mock(side_effect=LabError("lease lost"))
        with self.assertRaisesRegex(LabError, "lease lost"):
            world.toolbox.ensure("a" * 64, tools("a" * 64), POLICY)
        invalid = tools("a" * 64)
        invalid[0]["authorization"] = "not-a-real-token"
        with self.assertRaises(LabError):
            world.toolbox.ensure("a" * 64, invalid, POLICY)
        world.api.create_version.assert_not_called()

    def test_real_sdk_toolbox_creation_and_reads_use_authenticated_v1_routes(self):
        digest, state, requests = "a" * 64, {}, []
        name = NativeToolbox.name(digest)
        def wire(method, url, **kwargs):
            requests.append((method, url, kwargs))
            response = Response()
            response.headers["Content-Type"] = "application/json"
            response.raw, response._content_consumed = Mock(), True
            if method == "POST":
                body = parse_json(kwargs["data"])
                state.update({"id": "toolbox-version-1", "name": name, "version": "1",
                              "created_at": 1, **body})
                value, code = state, 200
            elif not state:
                value, code = {"error": {"code": "NotFound", "message": "Synthetic absence"}}, 404
            elif urlsplit(url).path.endswith("/versions"):
                value, code = {"data": [state], "has_more": False}, 200
            elif "/versions/1?" in url:
                value, code = state, 200
            else:
                value, code = {"id": "toolbox-1", "name": name, "default_version": "1",
                               "versions": {"latest": state}, "updated_at": 1}, 200
            response.status_code, response._content = code, canonical(value)
            return response
        credential = SimpleNamespace(get_token=lambda *args, **kwargs: AccessToken("offline-token", 9999999999))
        with AIProjectClient(PROJECT, credential, allow_preview=True, retry_total=0) as client, \
                patch("requests.Session.request", side_effect=wire):
            native = NativeToolbox(SimpleNamespace(client=client, target=TARGET), lambda: None)
            receipt = native.ensure(digest, tools(digest), POLICY)
        posts = [item for item in requests if item[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1], f"{PROJECT}/toolboxes/{name}/versions?api-version=v1")
        self.assertTrue(all(item[2]["headers"]["Authorization"] == "Bearer offline-token" for item in requests))
        self.assertTrue(all(item[0] in ("GET", "POST") for item in requests))
        lists = [item for item in requests if item[0] == "GET" and urlsplit(item[1]).path.endswith("/versions")]
        self.assertTrue(lists)
        self.assertTrue(all(parse_qs(urlsplit(item[1]).query) == {"api-version": ["v1"], "limit": ["2"]}
                            for item in lists))
        self.assertEqual(receipt["version"], "1")
