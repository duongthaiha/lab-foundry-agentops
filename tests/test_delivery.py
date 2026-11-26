import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from azure.ai.projects.models import PromptAgentDefinition
from agentops.contracts import LabError, canonical, fingerprint, parse_json
from agentops.delivery import connections, controls, definition, matrix, require_live_gate, validate_target, verify_source_revision
from agentops.delivery_azure import project_shape
from agentops.delivery_contracts import FEATURE, TOOL_NAME, load, release, save
from agentops.delivery_evaluation import grade
from agentops.delivery_knowledge import content_readback, desired_knowledge
from agentops.mcp_tool import FIXTURES


def observation(environment="dev"):
    fixture = {"feature_id": FEATURE, "environment": environment,
               "backend": "deterministic-lab-fixture", **FIXTURES[environment]}
    answer = {"announcement": "Microsoft announced Power Pages agents at Ignite 2024.",
              "citations": ["p0004"], **{key: value for key, value in fixture.items() if key != "backend"}}
    route = [{"type": "FixedRatio", "agent_version": "1", "traffic_percentage": 100}]
    return {
        "requested_version": "1", "route_before": route, "route_after": copy.deepcopy(route),
        "response": {"id": "response-test", "status": "completed",
                     "usage": {"input_tokens": 100, "output_tokens": 50},
                     "output": [
                         {"type": "mcp_call", "id": "kb-call", "server_label": "knowledge-base",
                          "name": "knowledge_base_retrieve", "status": "completed", "arguments": "{}",
                          "output": canonical({"references": [{"page_id": "p0004"}]}).decode()},
                         {"type": "mcp_call", "id": "tool-call", "server_label": "lab-tools",
                          "name": TOOL_NAME, "status": "completed",
                          "arguments": canonical({"feature_id": FEATURE}).decode(),
                          "output": canonical({"structuredContent": fixture}).decode()},
                         {"type": "message", "content": [{"type": "output_text", "text": canonical(answer).decode()}]},
                     ]},
    }


PRICES = {"input_per_million": 0.275, "output_per_million": 2.2,
          "tool_call_upper_bound_usd": 0.001, "safety_call_upper_bound_usd": 0.001,
          "provenance": "unit-test fixture; not a live price quote"}
SAFETY = dict.fromkeys(("Hate", "SelfHarm", "Sexual", "Violence"), 0)


class DeliveryTests(unittest.TestCase):
    def test_preparation_refuses_mismatched_or_dirty_source_revision(self):
        revision = "a" * 40
        for head, changes in ((revision, " M agentops/delivery.py"), (revision, "?? untracked.py"), ("b" * 40, "")):
            with patch("agentops.delivery.subprocess.run", side_effect=[
                Mock(returncode=0, stdout=head), Mock(returncode=0, stdout=changes),
            ]), self.assertRaisesRegex(LabError, "clean source checkout"):
                verify_source_revision(revision)
        with patch("agentops.delivery.subprocess.run", side_effect=[
            Mock(returncode=0, stdout=revision), Mock(returncode=0, stdout=""),
        ]):
            verify_source_revision(revision)

    def test_immutable_bundle_and_three_definitions(self):
        tools = [{"server_label": "knowledge-base"}, {"server_label": "lab-tools"}]
        for runtime in ("prompt", "hosted", "harness"):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as folder:
                image = "contoso.azurecr.io/lab@sha256:" + "c" * 64
                value = release(runtime, "a" * 40, "b" * 64, image=image)
                path, digest = save(value, Path(folder))
                self.assertEqual(load(path, digest), value)
                built = definition(value, tools, {"project_endpoint": "https://example.invalid"})
                if runtime == "harness":
                    self.assertEqual(built["harness"], {"type": "microsoft_copilot_preview"})
                    self.assertNotIn("container_configuration", built)
                    self.assertEqual(value["memory"], "unsupported-no-substitute")
                    serialized = PromptAgentDefinition(built).as_dict()
                    self.assertEqual(serialized["tools"][-1], {
                        "type": "microsoft_copilot_toolset_preview",
                        "default_config": {"enabled": False}, "configs": []})
                elif runtime == "hosted":
                    self.assertEqual(built["container_configuration"]["image"], image)
                else:
                    self.assertEqual(built["tools"], tools)
                path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaisesRegex(LabError, "changed release"):
                    load(path, digest)

    def test_unpinned_image_is_not_an_artifact(self):
        with self.assertRaisesRegex(LabError, "pinned ACR"):
            release("hosted", "a" * 40, "b" * 64, image="contoso.azurecr.io/lab:latest")

    def test_both_dependency_calls_and_correct_citations_are_mandatory(self):
        for index in (0, 1):
            value = observation()
            value["response"]["output"].pop(index)
            with self.assertRaisesRegex(LabError, "Both independently"):
                grade(value, "dev", ["p0004"], PRICES, 1, SAFETY)
        with self.assertRaisesRegex(LabError, "Citation was not returned"):
            grade(observation(), "dev", ["p0005"], PRICES, 1, SAFETY)

    def test_wrong_environment_and_empty_metrics_are_rejected(self):
        with self.assertRaisesRegex(LabError, "wrong environment"):
            grade(observation("test"), "dev", ["p0004"], PRICES, 1, SAFETY)
        for mutation in ("usage", "route", "latency", "price"):
            value, rates, elapsed = observation(), copy.deepcopy(PRICES), 1
            if mutation == "usage":
                del value["response"]["usage"]
            elif mutation == "route":
                value["route_after"] = []
            elif mutation == "latency":
                elapsed = 61
            else:
                rates["input_per_million"] = None
            with self.subTest(mutation=mutation), self.assertRaises(LabError):
                grade(value, "dev", ["p0004"], rates, elapsed, SAFETY)

    def test_safety_is_never_fabricated_from_a_successful_response(self):
        for environment in ("dev", "test", "labprod"):
            value = grade(observation(environment), environment, ["p0004"], PRICES, 1)
            self.assertEqual(value["structural_score"], 1)
            self.assertFalse(value["full_gate_passed"])
            self.assertTrue(value["blocking"])
        result = grade(observation(), "dev", ["p0004"], PRICES, 1, SAFETY)
        self.assertFalse(result["full_gate_passed"])
        self.assertNotIn("announcement", result)
        self.assertNotIn("Microsoft announced", canonical(result).decode())

    def test_undeclared_runtime_capability_is_rejected(self):
        value = observation()
        value["response"]["output"].append({"type": "local_shell_call"})
        with self.assertRaisesRegex(LabError, "Unexpected runtime capability"):
            grade(value, "dev", ["p0004"], PRICES, 1)

    def test_transport_evidence_from_a_different_release_is_rejected(self):
        value = observation()
        value["release_digest"] = "a" * 64
        call = value["response"]["output"][1]
        payload = parse_json(call["output"])
        payload["structuredContent"]["_auth"] = {
            "principal_digest": "c" * 64, "trace_id": "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa",
            "release_digest": "b" * 64}
        call["output"] = canonical(payload).decode()
        with self.assertRaisesRegex(LabError, "release binding"):
            grade(value, "dev", ["p0004"], PRICES, 1)

    def test_malformed_citation_is_a_domain_rejection(self):
        value = observation()
        part = value["response"]["output"][-1]["content"][0]
        answer = parse_json(part["text"])
        answer["citations"] = [{"text": "not a page locator"}]
        part["text"] = canonical(answer).decode()
        with self.assertRaisesRegex(LabError, "typed page locators"):
            grade(value, "dev", ["p0004"], PRICES, 1)

    def test_connection_and_runtime_tool_pin_the_same_release_route(self):
        foundry = Mock()
        foundry.target = {"search_endpoint": "https://unit.search.windows.net",
                         "tool_mcp_url": "https://unit.azurecontainerapps.io/mcp",
                         "tool_audience": "api://unit-test-only", "project_resource_id": "/synthetic-project"}
        with patch("agentops.delivery.ensure") as ensure:
            tools = connections(foundry, "a" * 64, {"kb": "kb-unit"})
        target = foundry.target["tool_mcp_url"] + "/releases/" + "a" * 64
        self.assertEqual(tools[1]["server_url"], target)
        self.assertEqual(ensure.call_args_list[1].args[2]["properties"]["target"], target)

    def test_knowledge_readback_detects_content_drift(self):
        pages = [{"page_id": "p0001", "page_number": 1, "title": "Fixture",
                  "source_url": "https://example.invalid", "content": "Synthetic unit-test source"}]
        service = Mock()
        service.request.return_value = {"@odata.count": 1, "value": pages}
        self.assertEqual(content_readback(service, "index", pages), fingerprint(pages))
        service.request.return_value = {"@odata.count": 1, "value": [{**pages[0], "content": "changed"}]}
        with self.assertRaisesRegex(LabError, "Indexed content differs"):
            content_readback(service, "index", pages)
        self.assertEqual(desired_knowledge("a" * 64)["kb"]["knowledgeSources"],
                         [{"name": "source-" + "a" * 20}])

    def test_default_server_fields_are_ignored_but_tool_changes_are_not(self):
        desired = {"tools": [{"type": "mcp", "allowed_tools": ["read"]}]}
        actual = {"tools": [{"type": "mcp", "allowed_tools": ["read"], "description": None}], "temperature": None}
        self.assertEqual(project_shape(actual, desired), desired)
        actual["tools"].append({"type": "shell"})
        with self.assertRaises(LabError):
            project_shape(actual, desired)

    def test_closed_controls_fail_before_loading_azure_credentials(self):
        with patch("agentops.delivery.controls", return_value={"live_ready": False}), \
                self.assertRaisesRegex(LabError, "Live controls are closed"):
            require_live_gate("123")
        with patch("agentops.delivery.controls", return_value={"platform_controls_ready": True}), \
                self.assertRaisesRegex(LabError, "execution is not enabled"):
            require_live_gate("123")
        self.assertTrue(all(row["native_serving_cutover"] == "unfulfilled"
                            for row in matrix()["tracks"].values()))

    def test_existing_real_settings_readback_requires_reviewers(self):
        def read(path):
            if "/workflows/" in path:
                return {"state": "disabled_manually"}
            if "/variables/" in path:
                return {"value": "false"}
            if path.endswith("deployment-branch-policies"):
                return {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}
            return {"protection_rules": [], "can_admins_bypass": False}
        with patch("agentops.delivery.gh", side_effect=read):
            result = controls()
        self.assertFalse(result["live_ready"])
        self.assertTrue(all(row["main_only"] and not row["admin_bypass"]
                            for row in result["environments"].values()))
