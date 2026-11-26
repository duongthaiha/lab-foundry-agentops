import copy
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from agentops.contracts import LabError, fingerprint
from agentops.delivery_contracts import release
from agentops.delivery_native import NativeDelivery, NativeRuntime, selected


def model(value):
    return SimpleNamespace(as_dict=lambda: copy.deepcopy(value))


def context(definition):
    return {"components_digest": fingerprint(definition), "content_digest": fingerprint("synthetic content"),
            "state_digest": fingerprint("unchanged"), "identity_digest": fingerprint("synthetic identity"),
            "policy_digest": fingerprint("synthetic policy")}


class Journal:
    def __init__(self):
        self.state, self.saved = {}, []

    @contextmanager
    def locked(self):
        yield self.state

    def save(self, state):
        self.saved.append(copy.deepcopy(state))

    def check(self):
        pass


class NativeFixture:
    """A service boundary fixture, not live Foundry evidence."""

    def __init__(self, runtime="prompt"):
        self.serving = "1"
        definition = {"kind": "hosted" if runtime == "hosted" else "prompt", "instructions": "baseline"}
        if runtime == "harness":
            definition["harness"] = {"type": "microsoft_copilot_preview"}
        self.versions = {"1": {"version": "1", "status": "active", "definition": definition}}
        self.foundry = MagicMock()
        self.agents = self.foundry.client.agents
        self.foundry.get_agent.side_effect = lambda name: self.details()
        self.foundry.get_version.side_effect = lambda name, version: copy.deepcopy(self.versions[version])
        self.agents.list_versions.side_effect = lambda *args, **kwargs: [
            model(version) for version in self.versions.values()]
        self.agents.create_version.side_effect = self.create
        self.agents.update_details.side_effect = self.update
        self.client = self.foundry.client.get_openai_client.return_value.__enter__.return_value
        self.client.conversations.create.return_value = SimpleNamespace(id="fresh-conversation")
        self.client.responses.create.side_effect = self.respond
        self.agents.create_session.return_value = model({"agent_session_id": "owned-session"})
        self.agents.get_session.return_value = model({
            "agent_session_id": "owned-session", "status": "active",
            "version_indicator": {"type": "version_ref", "agent_version": "2"}})
        self.runtime = NativeRuntime(self.foundry, lambda: None)

    def details(self):
        return {"state": "enabled", "configuration_state": "enabled",
                "instance_identity": {"principal_id": "synthetic-native-principal", "status": "active"},
                "agent_endpoint": {"version_selector": {"version_selection_rules": [
                    {"type": "FixedRatio", "agent_version": self.serving, "traffic_percentage": 100}]}}}

    def create(self, name, body, **kwargs):
        version = str(len(self.versions) + 1)
        value = {"version": version, "status": "active", **copy.deepcopy(body)}
        value["definition"]["service_default"] = None
        self.versions[version] = value
        return model(value)

    def update(self, name, body):
        self.serving = selected(body)

    def respond(self, **kwargs):
        response = {"status": "completed", "agent_reference": {"name": "contoso-prompt", "version": "2"}}
        if "agent_reference" in kwargs["extra_body"]:
            response["agent_reference"] = kwargs["extra_body"]["agent_reference"]
        else:
            response["agent_reference"]["name"] = "contoso-hosted"
            response["agent_session_id"] = kwargs["extra_body"]["agent_session_id"]
        return SimpleNamespace(model_dump=lambda **unused: copy.deepcopy(response))


class NativeDeliveryTests(unittest.TestCase):
    def setup_delivery(self, environment="dev", journal=None):
        world = NativeFixture()
        journal = journal or Journal()
        delivery = NativeDelivery(world.runtime, journal, context, environment)
        bundle = release("prompt", "a" * 40, "b" * 64)
        digest = fingerprint(bundle)
        definition = {"kind": "prompt", "instructions": bundle["instructions"]}
        return world, journal, delivery, bundle, digest, definition

    @staticmethod
    def consumer(candidate):
        return candidate["serving"]

    def test_rejection_preserves_serving_and_passing_cutover_is_retry_safe(self):
        world, journal, delivery, bundle, digest, definition = self.setup_delivery()
        rejected = delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": False})
        self.assertFalse(rejected["passed"])
        self.assertEqual(world.serving, "1")
        with self.assertRaisesRegex(LabError, "did not pass"):
            delivery.promote(digest, self.consumer, Mock())
        delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        self.assertEqual(world.agents.create_version.call_count, 1)
        first = delivery.promote(digest, self.consumer, Mock())
        self.assertEqual((first["before"]["version"], first["after"]["version"]), ("1", "2"))
        self.assertEqual(delivery.promote(digest, self.consumer, Mock()), first)
        self.assertEqual(world.agents.update_details.call_count, 1)
        result = delivery.rollback(bundle["agent"], self.consumer)
        self.assertEqual((result["before"]["version"], result["after"]["version"]), ("2", "1"))
        delivery.rollback(bundle["agent"], self.consumer)
        self.assertEqual(world.agents.update_details.call_count, 2)

    def test_failed_consumer_check_retains_rollback_intent_before_mutation(self):
        world, journal, delivery, bundle, digest, definition = self.setup_delivery()
        delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        with self.assertRaisesRegex(LabError, "Consumer did not confirm"):
            delivery.promote(digest, lambda candidate: {}, Mock())
        self.assertEqual(world.serving, "2")
        saved = [s for s in journal.saved if bundle["agent"] in s["native"]["dev"]["retained"]]
        self.assertEqual(saved[0]["native"]["dev"]["history"][-1]["status"], "started")
        self.assertEqual(saved[-1]["native"]["dev"]["history"][-1]["status"], "reconcile-required")
        self.assertEqual(delivery.rollback(bundle["agent"], self.consumer)["after"]["version"], "1")

    def test_after_effect_cutover_error_is_recoverable_without_blind_retry(self):
        world, journal, delivery, bundle, digest, definition = self.setup_delivery()
        delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        def ambiguous_update(name, body):
            world.update(name, body)
            raise TimeoutError("response lost after update")
        world.agents.update_details.side_effect = ambiguous_update
        with self.assertRaises(TimeoutError):
            delivery.promote(digest, self.consumer, Mock())
        self.assertEqual(world.serving, "2")
        world.agents.update_details.side_effect = world.update
        self.assertEqual(delivery.rollback(bundle["agent"], self.consumer)["after"]["version"], "1")

    def test_rollback_refuses_changed_state_without_replaying_old_memories(self):
        world, journal, delivery, bundle, digest, definition = self.setup_delivery()
        delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        delivery.promote(digest, self.consumer, Mock())
        delivery.inspect_context = lambda definition: {**context(definition), "state_digest": fingerprint("changed")}
        with self.assertRaisesRegex(LabError, "reconciliation"):
            delivery.rollback(bundle["agent"], self.consumer)
        self.assertEqual(world.serving, "2")
        self.assertEqual(world.agents.update_details.call_count, 1)

    def test_drift_invalidates_evidence_without_overwriting_retained_release(self):
        world, journal, delivery, bundle, digest, definition = self.setup_delivery()
        delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        world.versions["2"]["definition"]["instructions"] = "changed"
        with self.assertRaisesRegex(LabError, "definition changed"):
            delivery.promote(digest, self.consumer, Mock())
        world.agents.update_details.assert_not_called()
        self.assertEqual(journal.state["native"]["dev"]["retained"], {})

    def test_failed_reevaluation_cannot_reuse_earlier_pass(self):
        world, journal, delivery, bundle, digest, definition = self.setup_delivery()
        delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        world.client.responses.create.side_effect = LabError("incomplete")
        with self.assertRaisesRegex(LabError, "incomplete"):
            delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        self.assertNotIn(digest, journal.state["native"]["dev"]["candidates"])
        self.assertEqual(world.serving, "1")

    def test_next_environment_requires_identical_release_and_live_upstream_readback(self):
        world, journal, dev, bundle, digest, definition = self.setup_delivery()
        test_world, _, test, _, _, _ = self.setup_delivery("test", journal)
        test.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        with self.assertRaisesRegex(LabError, "Previous environment"):
            test.promote(digest, self.consumer, Mock())
        dev.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        dev.promote(digest, self.consumer, Mock())
        with self.assertRaisesRegex(LabError, "no longer serves"):
            test.promote(digest, self.consumer, lambda env, receipt: {})
        result = test.promote(digest, self.consumer, lambda env, receipt: world.runtime.snapshot(bundle["agent"]))
        self.assertEqual(result["release_digest"], digest)
        self.assertEqual(test_world.serving, "2")

    def test_native_request_routes_all_tracks_and_rejects_wrong_executed_version(self):
        for runtime in ("prompt", "hosted", "harness"):
            world = NativeFixture(runtime)
            observed_sessions = []
            before = world.runtime.snapshot("contoso-" + runtime)
            result = world.runtime.invoke_version(
                "contoso-" + runtime, "2", runtime, "question", "a" * 64, before, observed_sessions.append)
            self.assertEqual(result["route_before"], result["route_after"])
            kwargs = world.client.responses.create.call_args.kwargs
            self.assertEqual(kwargs["conversation"], "fresh-conversation")
            self.assertNotIn("previous_response_id", kwargs)
            if runtime == "hosted":
                self.assertEqual(observed_sessions[0]["session_id"], "owned-session")
                indicator = world.agents.create_session.call_args.kwargs["version_indicator"].as_dict()
                self.assertEqual(indicator, {"type": "version_ref", "agent_version": "2"})
            else:
                self.assertEqual(kwargs["extra_body"]["agent_reference"]["version"], "2")
                self.assertEqual(observed_sessions, [])
            if runtime == "harness":
                self.assertEqual(world.foundry.client.get_openai_client.call_args.kwargs["agent_name"], "contoso-harness")
            world.client.responses.create.side_effect = None
            world.client.responses.create.return_value = SimpleNamespace(model_dump=lambda **kwargs: {
                "status": "completed", "agent_reference": {"name": "contoso-" + runtime, "version": "1"}})
            with self.assertRaisesRegex(LabError, "did not confirm"):
                world.runtime.invoke_version(
                    "contoso-" + runtime, "2", runtime, "question", "a" * 64, before, observed_sessions.append)
            world.agents.update_details.assert_not_called()

    def test_session_is_recorded_before_activation_failure_and_foreign_drain_refused(self):
        world = NativeFixture("hosted")
        world.agents.get_session.return_value = model({
            "status": "failed", "version_indicator": {"type": "version_ref", "agent_version": "2"}})
        sessions = []
        with self.assertRaisesRegex(LabError, "activation failed"):
            world.runtime.session("contoso-hosted", "2", sessions.append)
        self.assertEqual(sessions[0]["session_id"], "owned-session")
        _, _, delivery, _, _, _ = self.setup_delivery()
        with self.assertRaisesRegex(LabError, "ownership"):
            delivery.drain("contoso-hosted", "another-session")

    def test_lost_lease_refuses_native_mutation(self):
        world = NativeFixture()
        world.versions["2"] = {**world.versions["1"], "version": "2"}
        before = world.runtime.snapshot("contoso-prompt")
        world.runtime.check_write = Mock(side_effect=LabError("lease lost"))
        with self.assertRaisesRegex(LabError, "lease lost"):
            world.runtime.cutover("contoso-prompt", "2", before)
        world.agents.update_details.assert_not_called()

    def test_harness_echoed_reference_cannot_authorize_native_promotion(self):
        world, journal = NativeFixture("harness"), Journal()
        delivery = NativeDelivery(world.runtime, journal, context, "dev")
        bundle = release("harness", "a" * 40, "b" * 64)
        definition = {"kind": "prompt", "harness": {"type": "microsoft_copilot_preview"},
                      "instructions": bundle["instructions"]}
        result = delivery.evaluate(bundle, fingerprint(bundle), definition, lambda item: {"full_gate_passed": True})
        self.assertFalse(result["passed"])
        self.assertIn("override is unverified", result["blocking"][0])
        self.assertEqual(world.serving, "1")

    def test_missing_component_content_state_identity_or_policy_evidence_blocks_creation(self):
        world, journal, delivery, bundle, digest, definition = self.setup_delivery()
        delivery.inspect_context = lambda definition: {}
        with self.assertRaises(LabError):
            delivery.evaluate(bundle, digest, definition, lambda item: {"full_gate_passed": True})
        world.agents.create_version.assert_not_called()
