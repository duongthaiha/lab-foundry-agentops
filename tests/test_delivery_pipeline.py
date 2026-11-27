"""Exercise the production orchestrator against service fixtures, not the simulator."""

import copy
import io
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agentops.contracts import LabError, canonical, fingerprint, parse_json
from agentops.delivery import REPO
from agentops.delivery_contracts import release
from agentops.delivery_pipeline import authorize, execute, main, public_receipt
from test_delivery import observation
from test_delivery_dev import GUID, configuration, infrastructure
from test_delivery_native import Journal, NativeFixture

NOW = datetime(2026, 11, 27, 1, tzinfo=timezone.utc)
PAGES = [{"page_id": "p0004", "page_number": 4, "content": "Synthetic source evidence.",
          "source_url": "https://unit.invalid", "title": "Synthetic test source"}]


def settings(environment="dev"):
    _, dev, _ = configuration()
    suffix = "prod" if environment == "labprod" else environment
    current = parse_json(canonical(dev).decode().replace("lab-dev/", f"lab-{suffix}/"))
    current["target"]["environment"] = environment
    if environment != "dev":
        for key in ("project_endpoint", "search_endpoint", "storage_endpoint", "tool_mcp_url"):
            current["target"][key] = current["target"][key].replace("unit.", f"unit-{suffix}.")
        for key in ("search_resource_id", "storage_resource_id", "tool_resource_id"):
            current[key] += "-" + suffix
    return {"current": current, "upstream": None if environment == "dev" else settings(
        "dev" if environment == "test" else "test")["current"]["target"],
        "journal_endpoint": dev["target"]["storage_endpoint"], "journal_resource_id": dev["storage_resource_id"]}


def policy(config, bundles):
    return {
        "mode": "prompt-delivery-v1", "id": "policy-" + config["current"]["target"]["environment"],
        "source_revision": "a" * 40, "binding_digest": fingerprint(config),
        "release_digests": [fingerprint(bundle) for bundle in bundles], "actions": ["promote", "rollback"],
        "valid_from": "2026-11-27T00:00:00Z", "expires_at": "2026-11-28T00:00:00Z",
        "price_checked_at": "2026-11-27T00:00:00Z", "spend_checked_at": "2026-11-27T00:00:00Z",
        "spend_observed_usd": 2, "estimated_monthly_usd": 260, "max_operations": 10, "allow_bootstrap": True,
    }


def bundle(revision="a", negative=False):
    return release("prompt", revision * 40, "b" * 64, negative=negative, tool_image_sha256="d" * 64)


class ServiceFixture(NativeFixture):
    def __init__(self, config):
        super().__init__()
        self.versions = {}
        self.exists = False
        self.config = config
        self.environment = config["current"]["target"]["environment"]
        self.foundry.target = config["current"]["target"]
        self.foundry.get_agent.side_effect = lambda name: self.details() if self.exists else None
        rows = infrastructure(config["current"])
        rows[4]["name"] = self.foundry.target["search_endpoint"].split("//")[1].split(".")[0]
        rows[5]["properties"].update({"supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2"})
        rows[6]["properties"]["template"]["containers"][0]["args"] = ["--environment", self.environment]
        rows[6]["properties"]["configuration"]["ingress"]["fqdn"] = (
            self.foundry.target["tool_mcp_url"].split("//")[1].split("/")[0])
        current = config["current"]
        project = current["target"]["project_resource_id"]
        account = project.split("/projects/")[0]
        self.arm = dict(zip((
            account, project, account + "/deployments/gpt-5-mini", account + "/raiPolicies",
            current["search_resource_id"], current["storage_resource_id"], current["tool_resource_id"],
        ), rows))
        self.arm[config["journal_resource_id"]] = {
            "location": "swedencentral", "sku": {"name": "Standard_LRS"}, "properties": {
                "primaryEndpoints": {"blob": config["journal_endpoint"] + "/"},
                "allowSharedKeyAccess": False, "allowBlobPublicAccess": False,
                "supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2",
            }}
        self.search = {}
        self.documents = {}
        self.foundry.arm.request.side_effect = lambda method, path, body=None, **kw: self.request(
            self.arm, method, path, body, **kw)
        self.foundry.search.request.side_effect = self.search_request
        self.judge_quality = 100

    def create(self, name, body, **kwargs):
        self.exists = True
        return super().create(name, body, **kwargs)

    def request(self, store, method, path, body=None, **kwargs):
        path = path.split("?")[0]
        if method == "GET":
            if path not in store and not kwargs.get("absent_ok"):
                raise LabError("Missing fixture resource")
            return copy.deepcopy(store.get(path))
        if method == "PUT":
            store[path] = copy.deepcopy(body)
            return {}
        raise AssertionError("Unexpected mutation: " + method)

    def search_request(self, method, path, body=None, **kwargs):
        clean = path.split("?")[0]
        if clean.endswith("/docs/index"):
            self.documents[clean.removesuffix("/docs/index")] = [
                {key: value for key, value in row.items() if key != "@search.action"} for row in body["value"]]
            return {"value": [{"status": True} for _ in body["value"]]}
        if clean.endswith("/docs/search"):
            rows = self.documents[clean.removesuffix("/docs/search")]
            return {"@odata.count": len(rows), "value": copy.deepcopy(rows)}
        return self.request(self.search, method, path, body, **kwargs)

    def respond(self, **kwargs):
        if kwargs.get("model"):
            verdict = {"quality": self.judge_quality, "Hate": 0, "SelfHarm": 0, "Sexual": 0, "Violence": 0}
            value = {"id": "synthetic-judge", "model": "gpt-5-mini", "status": "completed",
                     "usage": {"input_tokens": 100, "output_tokens": 20},
                     "output": [{"type": "message", "content": [
                         {"type": "output_text", "text": canonical(verdict).decode()}]}]}
        else:
            value = super().respond(**kwargs).model_dump()
            version = self.versions[value["agent_reference"]["version"]]
            value["usage"] = {"input_tokens": 100, "output_tokens": 20}
            if version["definition"].get("tool_choice") == "none":
                value["output"] = [{"type": "message", "content": [
                    {"type": "output_text", "text": "Not ready."}]}]
            else:
                value["output"] = observation(self.environment)["response"]["output"]
                result = parse_json(value["output"][1]["output"])
                result["structuredContent"]["_auth"] = {
                    "principal_digest": fingerprint({"principal_id": GUID}),
                    "trace_id": "11111111-2222-3333-4444-555555555555",
                    "release_digest": version["metadata"]["release_digest"],
                }
                value["output"][1]["output"] = canonical(result).decode()
        return SimpleNamespace(model_dump=lambda **unused: copy.deepcopy(value))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.bundles = [bundle("a"), bundle("b"), bundle("c", negative=True)]
        self.configs = {env: settings(env) for env in ("dev", "test", "labprod")}
        self.worlds = {env: ServiceFixture(config) for env, config in self.configs.items()}
        self.journal = Journal()
        self.journal.state["dev_smoke"] = {"preserved-history": {"used": 5}}
        self.counter = 0

    def run_stage(self, env, value, action="promote", **kwargs):
        self.counter += 1
        config = self.configs[env]
        return execute(
            self.worlds[env].foundry, self.journal, policy(config, self.bundles), config, value,
            fingerprint(value), f"123-{self.counter}-{env}-{action}", action,
            kwargs.get("reauthorize", lambda: None), kwargs.get("source_loader", lambda digest: PAGES),
            kwargs.get("upstream_check", lambda upstream, receipt:
                       self.worlds[upstream].runtime.snapshot(value["agent"])))

    def test_real_orchestrator_two_releases_three_environments_rejection_then_rollback(self):
        for value in self.bundles[:2]:
            receipts = [self.run_stage(env, value) for env in self.worlds]
            self.assertTrue(all(row["status"] == "promoted" and row["full_gate_passed"] for row in receipts))
            self.assertEqual({row["release_digest"] for row in receipts}, {fingerprint(value)})
        serving = {env: world.serving for env, world in self.worlds.items()}
        rejected = self.run_stage("dev", self.bundles[2])
        self.assertEqual(rejected["status"], "rejected")
        self.assertFalse(rejected["full_gate_passed"])
        self.assertEqual(serving, {env: world.serving for env, world in self.worlds.items()})
        restored = self.run_stage("labprod", self.bundles[1], "rollback")
        self.assertEqual(restored["status"], "rolled-back")
        self.assertEqual(restored["restored_release_digest"], fingerprint(self.bundles[0]))
        self.assertEqual(self.worlds["labprod"].serving, "2")
        self.assertEqual(self.journal.state["dev_smoke"], {"preserved-history": {"used": 5}})
        self.assertEqual(len(self.journal.state["delivery_pipeline"]["attempts"]), 8)
        self.assertNotIn("before", public_receipt(restored))
        self.assertNotIn("definitions", public_receipt(restored))

    def test_stage_retry_reuses_serving_receipt_without_creating_a_new_version(self):
        self.run_stage("dev", self.bundles[0])
        created = len(self.worlds["dev"].versions)
        result = self.run_stage("dev", self.bundles[0])
        self.assertEqual(result["status"], "promoted")
        self.assertTrue(result["idempotent"])
        self.assertEqual(len(self.worlds["dev"].versions), created)

    def test_no_upstream_promotion_blocks_cutover_even_with_passing_evaluation(self):
        with self.assertRaisesRegex(LabError, "Previous environment"):
            self.run_stage("test", self.bundles[0])
        self.assertEqual(self.worlds["test"].serving, "1")

    def test_low_semantic_quality_never_promotes(self):
        self.worlds["dev"].judge_quality = 30
        result = self.run_stage("dev", self.bundles[0])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.worlds["dev"].serving, "1")

    def test_rollback_recovers_after_effect_failure_without_rebuilding_or_deleting(self):
        self.run_stage("dev", self.bundles[0])
        world = self.worlds["dev"]
        def timeout_after_effect(name, body):
            world.update(name, body)
            raise TimeoutError("synthetic lost response")
        world.agents.update_details.side_effect = timeout_after_effect
        with self.assertRaises(TimeoutError):
            self.run_stage("dev", self.bundles[1])
        self.assertEqual(world.serving, "3")
        world.agents.update_details.side_effect = world.update
        created = world.agents.create_version.call_count
        rolled_back = self.run_stage("dev", self.bundles[1], "rollback")
        self.assertEqual((rolled_back["status"], world.serving), ("rolled-back", "2"))
        self.assertEqual(world.agents.create_version.call_count, created)
        self.assertTrue(all(row["status"] in ("promoted", "rolled-back")
                            for row in self.journal.state["delivery_pipeline"]["attempts"].values()))

    def test_retained_content_and_version_drift_block_rollback(self):
        self.run_stage("dev", self.bundles[0])
        self.run_stage("dev", self.bundles[1])
        self.worlds["dev"].versions["2"]["definition"]["instructions"] = "unreviewed"
        with self.assertRaisesRegex(LabError, "Retained native version changed"):
            self.run_stage("dev", self.bundles[1], "rollback")
        self.assertEqual(self.worlds["dev"].serving, "3")

    def test_rollback_checks_retained_bytes_without_downloading_or_reingesting_source(self):
        self.run_stage("dev", self.bundles[0])
        self.run_stage("dev", self.bundles[1])
        source = Mock(side_effect=AssertionError("Rollback must not contact the publisher"))
        self.assertEqual(self.run_stage("dev", self.bundles[1], "rollback", source_loader=source)["status"],
                         "rolled-back")
        source.assert_not_called()
        index = next(iter(self.worlds["dev"].documents.values()))
        index[0]["content"] = "Changed without a new content hash"
        with self.assertRaisesRegex(LabError, "watermark drift"):
            self.run_stage("dev", self.bundles[1], "rollback", source_loader=source)
        self.assertEqual(self.worlds["dev"].serving, "2")

    def test_new_policy_id_does_not_reset_usage_and_wrong_image_never_creates_agent(self):
        config = self.configs["dev"]
        changed = copy.deepcopy(self.bundles[0])
        changed["tool_image_sha256"] = "e" * 64
        with self.assertRaisesRegex(LabError, "MCP image"):
            execute(self.worlds["dev"].foundry, self.journal, policy(config, [changed]), config, changed,
                    fingerprint(changed), "image-test", "promote", lambda: None, Mock(), Mock())
        self.worlds["dev"].agents.create_version.assert_not_called()
        self.run_stage("dev", self.bundles[0])
        revised = {**policy(config, self.bundles), "id": "new-policy", "max_operations": 1}
        with self.assertRaisesRegex(LabError, "Lifetime operation allowance"):
            execute(self.worlds["dev"].foundry, self.journal, revised, config, self.bundles[1],
                    fingerprint(self.bundles[1]), "allowance-test", "promote", lambda: None, Mock(), Mock())

    def test_lost_authorization_prevents_any_resource_creation(self):
        with self.assertRaisesRegex(LabError, "revoked"):
            self.run_stage("dev", self.bundles[0], reauthorize=Mock(side_effect=LabError("revoked")))
        self.worlds["dev"].agents.create_version.assert_not_called()

    def test_source_loading_failure_is_terminal_before_target_mutation(self):
        source = Mock(side_effect=LabError("publisher unavailable"))
        with self.assertRaisesRegex(LabError, "publisher unavailable"):
            self.run_stage("dev", self.bundles[0], source_loader=source)

        attempt = next(iter(self.journal.state["delivery_pipeline"]["attempts"].values()))
        self.assertEqual(attempt["status"], "failed-before-mutation")
        self.assertFalse(attempt["mutation_started"])
        self.worlds["dev"].agents.create_version.assert_not_called()
        self.assertEqual(self.worlds["dev"].documents, {})

        result = self.run_stage("dev", self.bundles[0])
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(len(self.journal.state["delivery_pipeline"]["attempts"]), 2)

    def test_verified_pre_cutover_failure_does_not_deadlock_pipeline(self):
        with patch("agentops.delivery_pipeline.materialize", side_effect=LabError("partial materialization")):
            with self.assertRaisesRegex(LabError, "partial materialization"):
                self.run_stage("dev", self.bundles[0])

        attempt = next(iter(self.journal.state["delivery_pipeline"]["attempts"].values()))
        self.assertEqual(attempt["status"], "failed-before-cutover")
        self.assertTrue(attempt["mutation_started"])
        self.assertTrue(attempt["verified_serving_unchanged"])
        self.assertFalse(self.worlds["dev"].exists)

        result = self.run_stage("dev", self.bundles[0])
        self.assertEqual(result["status"], "promoted")

    def test_uncertain_rollback_can_be_retried_after_cutover_effect(self):
        self.run_stage("dev", self.bundles[0])
        self.run_stage("dev", self.bundles[1])
        world = self.worlds["dev"]

        def timeout_after_effect(name, body):
            world.update(name, body)
            raise TimeoutError("synthetic lost rollback response")

        world.agents.update_details.side_effect = timeout_after_effect
        with self.assertRaisesRegex(TimeoutError, "lost rollback response"):
            self.run_stage("dev", self.bundles[1], "rollback")
        world.agents.update_details.side_effect = world.update
        created = world.agents.create_version.call_count

        retried = self.run_stage("dev", self.bundles[1], "rollback")
        self.assertEqual((retried["status"], world.serving), ("rolled-back", "2"))
        self.assertEqual(world.agents.create_version.call_count, created)
        self.assertTrue(all(row["status"] in ("promoted", "rolled-back")
                            for row in self.journal.state["delivery_pipeline"]["attempts"].values()))


class AuthorizationTests(unittest.TestCase):
    def auth(self, environment="dev", action="promote", mutate=None):
        config, value = settings(environment), bundle()
        bounds = policy(config, [value])
        path = ".github/workflows/" + ("promote.yml" if action == "promote" else "rollback.yml")
        env = {
            "LIVE_DELIVERY_ENABLED": "true", "DELIVERY_POLICY": canonical(bounds).decode(),
            "DELIVERY_BINDING": canonical(config).decode(), "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": REPO, "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": f"{REPO}/{path}@refs/heads/main", "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
        }
        def read(route):
            if route.endswith("/runs/123"):
                result = {"workflow_id": 456, "path": path, "head_branch": "main", "event": "workflow_dispatch",
                          "status": "in_progress", "run_attempt": 1, "head_sha": "a" * 40}
            elif "/workflows/" in route:
                result = {"state": "active", "id": 456}
            elif route.endswith("/heads/main"):
                result = {"object": {"sha": "a" * 40}}
            elif route.endswith("/deployment-branch-policies"):
                result = {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}
            elif route.endswith("/approvals"):
                result = [{"state": "approved", "user": {"login": "duongthaiha"},
                           "environments": [{"name": environment}]}]
            else:
                result = {"can_admins_bypass": False, "deployment_branch_policy": {
                    "protected_branches": False, "custom_branch_policies": True},
                    "protection_rules": [{"type": "required_reviewers",
                                          "reviewers": [{"reviewer": {"login": "duongthaiha"}}]}]}
            return mutate(route, result) if mutate else result
        return env, bounds, config, read, fingerprint(value)

    def test_each_stage_and_rollback_use_reviewed_environment_and_human_prod_approval(self):
        for environment in ("dev", "test", "labprod"):
            for action in ("promote", "rollback"):
                env, bounds, config, read, digest = self.auth(environment, action)
                self.assertEqual(authorize(env, environment, action, digest, read, NOW), (bounds, config))
        for action in ("promote", "rollback"):
            env, _, _, read, digest = self.auth("labprod", action, lambda route, result:
                                               [] if route.endswith("/approvals") else result)
            with self.assertRaisesRegex(LabError, "no recorded human approval"):
                authorize(env, "labprod", action, digest, read, NOW)

    def test_closed_or_spoofed_workflow_fails_before_any_github_or_azure_access(self):
        env, _, _, _, digest = self.auth()
        for key, value in (("LIVE_DELIVERY_ENABLED", "false"), ("GITHUB_EVENT_NAME", "pull_request"),
                           ("GITHUB_WORKFLOW_REF", "arbitrary"), ("GITHUB_ACTIONS", "false")):
            read = Mock()
            with self.subTest(key=key), self.assertRaises(LabError):
                authorize({**env, key: value}, "dev", "promote", digest, read, NOW)
            read.assert_not_called()
        with patch.dict("os.environ", {}, clear=True), patch("sys.argv", [
            "pipeline", "run", "--environment", "dev", "--action", "promote",
            "--bundle", "absent.json", "--digest", digest,
        ]), patch("sys.stderr", io.StringIO()), patch("azure.identity.AzureCliCredential") as credential:
            self.assertEqual(main(), 1)
        credential.assert_not_called()

    def test_changed_image_release_bounds_or_journal_are_not_accepted(self):
        env, bounds, config, read, digest = self.auth()
        for change in ({"expires_at": "2026-11-26T00:00:00Z"}, {"max_operations": 11},
                       {"release_digests": ["e" * 64]}, {"spend_observed_usd": 30},
                       {"estimated_monthly_usd": 501}):
            with self.subTest(change=change), self.assertRaises(LabError):
                authorize({**env, "DELIVERY_POLICY": canonical({**bounds, **change}).decode()},
                          "dev", "promote", digest, read, NOW)
        config["journal_endpoint"] = "https://other.blob.core.windows.net"
        bounds["binding_digest"] = fingerprint(config)
        with self.assertRaisesRegex(LabError, "Journal endpoint"):
            authorize({**env, "DELIVERY_POLICY": canonical(bounds).decode(),
                       "DELIVERY_BINDING": canonical(config).decode()}, "dev", "promote", digest, read, NOW)


if __name__ == "__main__":
    unittest.main()
