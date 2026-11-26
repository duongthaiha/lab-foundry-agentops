import copy
import io
import unittest
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx2 as httpx
import jwt
from azure.ai.projects import AIProjectClient
from azure.core.credentials import AccessToken
from cryptography.hazmat.primitives.asymmetric import rsa

from agentops.contracts import LabError, canonical, fingerprint, parse_json
from agentops.delivery import REPO
from agentops.delivery_contracts import FEATURE, MAX_OUTPUT_TOKENS, release
from agentops.delivery_dev import (
    JUDGE_SCHEMA, WORKFLOW, authorize, inspect_dev, judge_response, main, run_smoke, verify_ci_identity,
)
from agentops.mcp_tool import FIXTURES
from test_delivery import PRICES, observation
from test_delivery_native import Journal, NativeFixture

NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
GUID = "11111111-2222-3333-4444-555555555555"
PREFIX = f"/subscriptions/{GUID}/resourceGroups/foudnry-agentops-lab-dev/providers/"
FIXTURE = {"feature_id": FEATURE, "environment": "dev", "backend": "deterministic-lab-fixture", **FIXTURES["dev"]}


def configuration():
    binding = {
        "tenant_id": GUID, "client_id": GUID, "subscription_id": GUID,
        "search_resource_id": PREFIX + "Microsoft.Search/searchServices/unit",
        "storage_resource_id": PREFIX + "Microsoft.Storage/storageAccounts/unit",
        "tool_resource_id": PREFIX + "Microsoft.App/containerApps/unit",
        "tool_image": "unit.azurecr.io/mcp@sha256:" + "d" * 64,
        "target": {
            "environment": "dev", "project_endpoint": "https://unit.services.ai.azure.com/api/projects/unit",
            "project_resource_id": PREFIX + "Microsoft.CognitiveServices/accounts/unit/projects/unit",
            "search_endpoint": "https://unit.search.windows.net",
            "storage_endpoint": "https://unit.blob.core.windows.net",
            "tool_mcp_url": "https://unit.azurecontainerapps.io/mcp", "tool_audience": "api://" + GUID,
            "prices": {**PRICES, "provenance": "https://prices.azure.com/api/retail/prices"},
        },
    }
    policy = {
        "mode": "dev-unattended-v1", "id": "unit-dev-policy",
        "source_revision": "a" * 40, "source_sha256": "b" * 64,
        "binding_digest": fingerprint(binding), "valid_from": "2026-11-26T00:00:00Z",
        "expires_at": "2026-11-27T00:00:00Z", "price_checked_at": "2026-11-26T00:00:00Z",
        "max_runs": 2, "monthly_ceiling_usd": 500, "estimated_monthly_usd": 110,
        "max_case_usd": 0.05,
    }
    env = {"LIVE_DEV_SMOKE_ENABLED": "true", "DEV_SMOKE_POLICY": canonical(policy).decode(),
           "DEV_SMOKE_BINDING": canonical(binding).decode(),
           "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPO, "GITHUB_REF": "refs/heads/main",
           "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_REF": f"{REPO}/{WORKFLOW}@refs/heads/main",
           "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40}
    return policy, binding, env


def github(path):
    if path.endswith("/runs/123"):
        return {"workflow_id": 456, "path": WORKFLOW, "event": "workflow_dispatch", "head_branch": "main",
                "status": "in_progress", "run_attempt": 1, "head_sha": "a" * 40}
    if path.endswith("/dev-smoke.yml"):
        return {"state": "active", "id": 456}
    if path.endswith("/heads/main"):
        return {"object": {"sha": "a" * 40}}
    if path.endswith("/deployment-branch-policies"):
        return {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}
    return {"can_admins_bypass": False, "protection_rules": [],
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}


def infrastructure(binding):
    target = binding["target"]
    resources = [
        {"location": "swedencentral", "properties": {"disableLocalAuth": True}},
        {"location": "swedencentral", "identity": {"principalId": GUID},
         "properties": {"endpoints": {"AI Foundry API": target["project_endpoint"]}}},
        {"sku": {"name": "DataZoneStandard", "capacity": 10}, "properties": {
            "model": {"format": "OpenAI", "name": "gpt-5-mini", "version": "2025-08-07"},
            "raiPolicyName": "Microsoft.DefaultV2", "versionUpgradeOption": "NoAutoUpgrade"}},
        {"value": [{"name": "Microsoft.DefaultV2", "properties": {"contentFilters": [
            {"name": "Jailbreak", "source": "Prompt", "enabled": True, "blocking": True}]}}]},
        {"name": "unit", "location": "swedencentral", "sku": {"name": "basic"},
         "properties": {"disableLocalAuth": True, "replicaCount": 1, "partitionCount": 1}},
        {"location": "swedencentral", "sku": {"name": "Standard_LRS"},
         "properties": {"allowSharedKeyAccess": False, "allowBlobPublicAccess": False,
                        "primaryEndpoints": {"blob": target["storage_endpoint"] + "/"}}},
        {"location": "swedencentral", "properties": {
            "workloadProfileName": "Consumption", "configuration": {"ingress": {"fqdn": "unit.azurecontainerapps.io"}},
            "template": {"scale": {"minReplicas": 0, "maxReplicas": 1}, "containers": [{
                "image": binding["tool_image"], "resources": {"cpu": 0.25, "memory": "0.5Gi"},
                "args": ["--environment", "dev"], "env": [
                    {"name": "AZURE_TENANT_ID", "value": GUID},
                    {"name": "MCP_AUDIENCE", "value": target["tool_audience"]},
                    {"name": "MCP_ALLOWED_CALLER_IDS", "value": GUID}]}]}}},
    ]
    return resources


class DevPolicyTests(unittest.TestCase):
    def test_expiring_dev_policy_works_without_reviewers_and_with_them_restored(self):
        policy, binding, env = configuration()
        self.assertEqual(authorize(env, github, NOW), (policy, binding))
        def restored(path):
            value = github(path)
            if "protection_rules" in value:
                value["protection_rules"] = [{"type": "required_reviewers"}]
            return value
        self.assertEqual(authorize(env, restored, NOW), (policy, binding))

    def test_untrusted_context_or_disabled_flag_fails_before_github_or_credentials(self):
        _, _, original = configuration()
        for key, value in (("LIVE_DEV_SMOKE_ENABLED", "false"), ("GITHUB_EVENT_NAME", "pull_request"),
                           ("GITHUB_REF", "refs/heads/work"), ("GITHUB_WORKFLOW_REF", "simulated-rehearsal.yml"),
                           ("GITHUB_ACTIONS", "false")):
            env = {**original, key: value}
            read = Mock()
            with self.subTest(key=key), self.assertRaises(LabError):
                authorize(env, read, NOW)
            read.assert_not_called()

    def test_rejects_expired_overspend_wrong_target_and_placeholder_policy(self):
        policy, binding, env = configuration()
        for key, value in (("expires_at", "2026-11-26T10:00:00Z"), ("monthly_ceiling_usd", 501),
                           ("estimated_monthly_usd", 501), ("max_runs", 11), ("max_case_usd", 0.06),
                           ("source_revision", "main"), ("mode", "simulated")):
            candidate = {**policy, key: value}
            with self.subTest(key=key), self.assertRaises(LabError):
                authorize({**env, "DEV_SMOKE_POLICY": canonical(candidate).decode()}, github, NOW)
        binding["target"]["environment"] = "test"
        policy["binding_digest"] = fingerprint(binding)
        with self.assertRaisesRegex(LabError, "target environment"):
            authorize({**env, "DEV_SMOKE_POLICY": canonical(policy).decode(),
                       "DEV_SMOKE_BINDING": canonical(binding).decode()}, github, NOW)

    def test_live_run_readback_rejects_changed_main_wrong_workflow_and_protection_drift(self):
        _, _, env = configuration()
        for route, mutation in (
            ("/runs/123", {"workflow_id": 999}), ("/runs/123", {"run_attempt": 2}),
            ("/heads/main", {"object": {"sha": "c" * 40}}),
            ("/environments/dev", {"can_admins_bypass": True}),
            ("/deployment-branch-policies", {"total_count": 2}),
            ("/dev-smoke.yml", {"state": "disabled_manually"}),
        ):
            def read(path):
                value = github(path)
                return {**value, **mutation} if path.endswith(route) else value
            with self.subTest(route=route, mutation=mutation), self.assertRaises(LabError):
                authorize(env, read, NOW)

    def test_actual_cli_rejects_closed_flag_without_source_download_or_azure(self):
        for command in ("authorize", "run"):
            output = io.StringIO()
            with patch.dict("os.environ", {}, clear=True), patch("sys.argv", ["dev", command]), \
                    patch("sys.stderr", output), patch("agentops.delivery_dev.acquire_source") as source, \
                    patch("azure.identity.AzureCliCredential") as credential:
                self.assertEqual(main(), 1)
            self.assertIn("disabled", output.getvalue())
            source.assert_not_called()
            credential.assert_not_called()

    def test_resource_preflight_is_read_only_and_refuses_auth_policy_and_size_drift(self):
        _, binding, _ = configuration()
        for mutation in (None, "max-capacity", "auth", "policy", "policy-missing", "policy-duplicate",
                         "policy-paged", "capacity", "endpoint", "scale", "caller"):
            resources = infrastructure(binding)
            policies = resources[3]
            if mutation == "auth":
                resources[0]["properties"]["disableLocalAuth"] = False
            elif mutation == "policy":
                policies["value"][0]["properties"]["contentFilters"][0]["blocking"] = False
            elif mutation == "policy-missing":
                policies["value"][0]["name"] = "Microsoft.Default"
            elif mutation == "policy-duplicate":
                policies["value"].append(copy.deepcopy(policies["value"][0]))
            elif mutation == "policy-paged":
                policies["nextLink"] = "https://management.azure.com/next"
            elif mutation in ("max-capacity", "capacity"):
                resources[2]["sku"]["capacity"] = 100 if mutation == "max-capacity" else 101
            elif mutation == "endpoint":
                resources[1]["properties"]["endpoints"]["AI Foundry API"] += "-other"
            elif mutation == "scale":
                resources[6]["properties"]["template"]["scale"]["maxReplicas"] = 2
            elif mutation == "caller":
                resources[6]["properties"]["template"]["containers"][0]["env"][-1]["value"] = "other"
            foundry = Mock()
            foundry.arm.request.side_effect = resources
            if mutation in (None, "max-capacity"):
                self.assertEqual(inspect_dev(foundry, binding), fingerprint({"principal_id": GUID}))
            else:
                with self.subTest(mutation=mutation), self.assertRaises(LabError):
                    inspect_dev(foundry, binding)
            self.assertTrue(all(call.args[0] == "GET" for call in foundry.arm.request.call_args_list))

    def test_signed_app_token_required_not_user_login_or_forged_action_environment(self):
        _, binding, _ = configuration()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for mutation in (None, "user", "wrong-app", "signature", "expired"):
            claims = {"ver": "1.0", "tid": GUID, "oid": GUID, "appid": GUID,
                      "iss": f"https://sts.windows.net/{GUID}/", "aud": "https://management.azure.com/",
                      "iat": int(time.time()) - 10, "nbf": int(time.time()) - 10, "exp": int(time.time()) + 600}
            if mutation == "user":
                claims["scp"] = "user_impersonation"
            if mutation == "wrong-app":
                claims["appid"] = "another-app"
            if mutation == "expired":
                claims["exp"] = int(time.time()) - 1
            token = jwt.encode(claims, other if mutation == "signature" else key, algorithm="RS256")
            credential = SimpleNamespace(get_token=lambda *a, **k: AccessToken(token, claims["exp"]))
            with patch("jwt.PyJWKClient") as jwks:
                jwks.return_value.get_signing_key_from_jwt.return_value.key = key.public_key()
                if mutation is None:
                    verify_ci_identity(credential, binding)
                else:
                    with self.subTest(mutation=mutation), self.assertRaises(LabError):
                        verify_ci_identity(credential, binding)


def smoke_fixture():
    policy, binding, _ = configuration()
    bundle = release("prompt", policy["source_revision"], policy["source_sha256"])
    digest = fingerprint(bundle)
    world, journal = NativeFixture(), Journal()
    world.versions.clear()
    world.foundry.target = binding["target"]
    world.foundry.get_agent.side_effect = lambda name: world.details() if world.versions else None
    response = observation()["response"]
    response["agent_reference"] = {"name": "dev-smoke-" + digest[:20], "version": "1"}
    payload = parse_json(response["output"][1]["output"])
    payload["structuredContent"]["_auth"] = {
        "principal_digest": fingerprint({"principal_id": GUID}),
        "trace_id": "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa", "release_digest": digest}
    response["output"][1]["output"] = canonical(payload).decode()
    world.client.responses.create.side_effect = lambda **kwargs: SimpleNamespace(
        model_dump=lambda **unused: copy.deepcopy(response))
    pages = [{"page_id": "p0004", "content": "Synthetic source; not publisher text"}]
    knowledge = {"page_ids": ["p0004"], "index": "index-test", "source": "source-test", "kb": "kb-test"}
    return policy, binding, bundle, world, journal, response, pages, knowledge


class DevSmokeTests(unittest.TestCase):
    def execute(self, setup, run_key="123-1"):
        policy, binding, bundle, world, journal, _, pages, knowledge = setup
        with patch("agentops.delivery_dev.inspect_dev", return_value=fingerprint({"principal_id": GUID})), \
                patch("agentops.delivery_dev.materialize", return_value=knowledge), \
                patch("agentops.delivery_dev.connections", return_value=[]), \
                patch("agentops.delivery_dev.verify_knowledge"), \
                patch("agentops.delivery_dev.judge_response", return_value={"quality": 1}) as judge:
            result = run_smoke(world.foundry, journal, policy, binding, bundle, pages, run_key, Mock())
        return result, judge

    def test_success_is_scoped_smoke_not_promotion_and_reuses_version_without_route_write(self):
        setup = smoke_fixture()
        result, judge = self.execute(setup)
        self.assertEqual(result["status"], "smoke-passed")
        self.assertFalse(result["full_gate_passed"])
        self.assertFalse(result["promotion_authorized"])
        self.assertEqual(result["semantic"]["quality"], 1)
        self.assertEqual(judge.call_count, 1)
        world, journal = setup[3], setup[4]
        self.assertNotIn("native", journal.state)
        self.assertTrue(all(call.args[0].startswith("dev-smoke-")
                            for call in world.agents.create_version.call_args_list))
        world.agents.update_details.reset_mock()
        self.execute(setup, "124-1")
        world.agents.update_details.assert_not_called()
        self.assertEqual(world.agents.create_version.call_count, 1)
        with self.assertRaisesRegex(LabError, "allowance exhausted"):
            self.execute(setup, "125-1")

    def test_missing_dependency_wrong_identity_version_and_usage_never_reach_judge(self):
        for mutation in ("knowledge", "tool", "identity", "version", "usage"):
            setup = smoke_fixture()
            response = setup[5]
            if mutation in ("knowledge", "tool"):
                response["output"].pop(0 if mutation == "knowledge" else 1)
            elif mutation == "identity":
                payload = parse_json(response["output"][1]["output"])
                payload["structuredContent"]["_auth"]["principal_digest"] = "c" * 64
                response["output"][1]["output"] = canonical(payload).decode()
            elif mutation == "version":
                response["agent_reference"]["version"] = "2"
            else:
                response.pop("usage")
            with self.subTest(mutation=mutation), self.assertRaises(LabError):
                self.execute(setup)
            attempt = setup[4].state["dev_smoke"][setup[0]["id"]]["attempts"]["123-1"]
            self.assertEqual(attempt["status"], "reconcile-required")
            self.assertFalse(attempt["full_gate_passed"])
            with self.assertRaisesRegex(LabError, "reconcile before another run"):
                self.execute(setup, "124-1")

    def test_lease_or_policy_loss_stops_before_agent_create(self):
        setup = smoke_fixture()
        policy, binding, bundle, world, journal, _, pages, _ = setup
        with patch("agentops.delivery_dev.inspect_dev"), self.assertRaisesRegex(LabError, "revoked"):
            run_smoke(world.foundry, journal, policy, binding, bundle, pages, "123-1",
                      Mock(side_effect=LabError("revoked")))
        world.agents.create_version.assert_not_called()
        self.assertEqual(journal.state, {})

    def test_existing_unowned_agent_never_repaired(self):
        setup = smoke_fixture()
        setup[3].versions["1"] = {"version": "1", "metadata": {}, "definition": {}, "status": "active"}
        with self.assertRaisesRegex(LabError, "ownership"):
            self.execute(setup)
        setup[3].agents.update_details.assert_not_called()
        setup[3].agents.create_version.assert_not_called()

    def test_creation_timeout_is_reserved_and_never_retried_even_under_new_policy(self):
        setup = smoke_fixture()
        setup[3].agents.create_version.side_effect = TimeoutError("uncertain creation")
        with self.assertRaises(TimeoutError):
            self.execute(setup)
        attempt = setup[4].state["dev_smoke"][setup[0]["id"]]["attempts"]["123-1"]
        self.assertIn("planned_resources", attempt)
        self.assertEqual(attempt["reserved_usd"], 0.05)
        setup[0]["id"] = "another-policy"
        with self.assertRaisesRegex(LabError, "reconcile before another run"):
            self.execute(setup, "124-1")
        self.assertEqual(setup[3].agents.create_version.call_count, 1)

    def test_smoke_sdk_uses_fresh_conversation_pinned_endpoint_and_two_call_limit(self):
        setup = smoke_fixture()
        policy, binding, bundle, world, journal, response, pages, knowledge = setup
        requests = []
        def wire(request):
            requests.append(request)
            if request.url.path.endswith("/conversations"):
                return httpx.Response(200, json={"id": "wire-conversation", "object": "conversation", "created_at": 1})
            return httpx.Response(200, json={"object": "response", **response})
        credential = SimpleNamespace(get_token=lambda *a, **k: AccessToken("offline-token", 9999999999))
        with AIProjectClient(binding["target"]["project_endpoint"], credential, allow_preview=True) as project, \
                httpx.Client(transport=httpx.MockTransport(wire)) as http:
            world.foundry.client.get_openai_client.side_effect = lambda **kwargs: project.get_openai_client(
                http_client=http, **kwargs)
            result, _ = self.execute(setup)
        self.assertEqual(result["conversation_id"], "wire-conversation")
        self.assertTrue(all("/agents/dev-smoke-" in str(request.url) for request in requests))
        self.assertTrue(all(request.headers["Authorization"] == "Bearer offline-token" for request in requests))
        body = parse_json(requests[-1].content)
        self.assertEqual(body["max_tool_calls"], 2)
        self.assertEqual(body["max_output_tokens"], MAX_OUTPUT_TOKENS)
        self.assertEqual(body["conversation"], "wire-conversation")
        self.assertFalse({"agent_reference", "model", "previous_response_id"} & body.keys())

    def test_judge_uses_actual_sdk_auth_structured_output_and_exact_response_binding(self):
        setup = smoke_fixture()
        _, binding, bundle, _, _, observed, pages, _ = setup
        requests = []
        verdict = {"quality": 80, "Hate": 0, "SelfHarm": 0, "Sexual": 0, "Violence": 0}
        def wire(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "judge-response", "object": "response", "model": "gpt-5-mini-2025-08-07",
                "status": "completed", "usage": {"input_tokens": 200, "output_tokens": 100},
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": canonical(verdict).decode()}]}],
            })
        credential = SimpleNamespace(get_token=lambda *a, **k: AccessToken("offline-token", 9999999999))
        with AIProjectClient(binding["target"]["project_endpoint"], credential, allow_preview=True) as project, \
                httpx.Client(transport=httpx.MockTransport(wire)) as http:
            foundry = SimpleNamespace(target=binding["target"], client=Mock())
            foundry.client.get_openai_client.side_effect = lambda **kwargs: project.get_openai_client(http_client=http, **kwargs)
            structural = {"citations": ["p0004"], "cost_upper_bound_usd": 0.001, "fixture": FIXTURE}
            result = judge_response(foundry, bundle, {"response": observed}, pages, structural, Mock())
        body = parse_json(requests[0].content)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer offline-token")
        self.assertEqual(body["text"]["format"]["schema"], JUDGE_SCHEMA)
        self.assertEqual(body["tools"], [])
        self.assertFalse(body["store"])
        self.assertEqual(body["max_output_tokens"], MAX_OUTPUT_TOKENS)
        evidence = parse_json(body["input"])
        self.assertEqual(evidence["answer"], observed["output"][-1]["content"][0]["text"])
        # The lab half of the answer is judged against the separately verified tool fixture.
        self.assertEqual(evidence["lab_fixture_result"], FIXTURE)
        self.assertEqual(evidence["source_pages"], pages)
        self.assertEqual(result["subject_digest"], fingerprint(observed))
        self.assertEqual(result["quality"], 0.8)
        self.assertNotIn("source_pages", result)

    def test_judge_fails_closed_for_low_quality_unsafe_or_unmeasured_output(self):
        setup = smoke_fixture()
        _, binding, bundle, world, _, observed, pages, _ = setup
        for mutation in ("quality", "safety", "usage", "cost", "refusal"):
            verdict = {"quality": 100, "Hate": 0, "SelfHarm": 0, "Sexual": 0, "Violence": 0}
            if mutation == "quality":
                verdict["quality"] = 79
            if mutation == "safety":
                verdict["Violence"] = 1
            response = {"id": "judge-1", "model": "gpt-5-mini", "status": "completed",
                        "usage": {"input_tokens": 10, "output_tokens": 10},
                        "output": [{"type": "message", "content": [
                            {"type": "output_text", "text": canonical(verdict).decode()}]}]}
            if mutation == "usage":
                response.pop("usage")
            if mutation == "cost":
                response["usage"]["input_tokens"] = 10000000
            if mutation == "refusal":
                response["output"] = []
            world.client.responses.create.side_effect = lambda **kwargs: SimpleNamespace(
                model_dump=lambda **unused: response)
            with self.subTest(mutation=mutation), self.assertRaises(LabError):
                judge_response(world.foundry, bundle, {"response": observed}, pages,
                               {"citations": ["p0004"], "cost_upper_bound_usd": 0.001, "fixture": FIXTURE}, Mock())


if __name__ == "__main__":
    unittest.main()
