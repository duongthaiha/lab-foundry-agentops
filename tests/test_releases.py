import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentops import artifacts, bindings
from agentops.contracts import LabError, canonical, read_json, utc_now
from agentops.examples import write_example
from agentops.evaluation import evaluate
from agentops.releases import ReleaseLab


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lab = ReleaseLab(self.root / "lab")
        self.bundle_paths = {}
        for runtime in ("prompt", "hosted", "harness"):
            for version in ("1", "2"):
                source = self.root / (runtime + version)
                write_example(source, runtime, "a" * 40, version)
                self.bundle_paths[runtime, version] = artifacts.build(source, self.root / "bundles")

    def create(self, runtime="prompt", environment="dev", version="1", readiness=None):
        path, digest = self.bundle_paths[runtime, version]
        bundle = artifacts.load(path, digest)
        binding, content, state = bindings.synthetic_records(bundle, environment)
        ready = readiness or {
            "evidence_type": "simulated", "identity": "synthetic-runtime",
            "access": True, "status": "completed",
        }
        result = self.lab.create(path, digest, binding, content, state, ready)
        self.assertEqual(result["serving_before"], result["serving_during"])
        self.assertEqual(result["serving_before"], result["serving_after"])
        return result["candidate_id"]

    def report(self, candidate_id, **metrics):
        return {
            "evidence_type": "simulated", "status": "completed",
            "context": self.lab.candidate(candidate_id)["context"], "completed_at": utc_now(),
            "metrics": {"quality": 1, "unsafe": 0, "latency_ms": 100, "cost_usd": 0.001, **metrics},
        }

    def approve(self, candidate_id):
        self.lab.record_evaluation(candidate_id, self.report(candidate_id))
        self.lab.approve(candidate_id, "synthetic-reviewer")

    def promote(self, candidate_id, rollback=False):
        context = self.lab.candidate(candidate_id)["context"]
        return self.lab.promote(candidate_id, self.lab.serving(context["agent"], context["environment"]),
                                rollback=rollback)

    def test_three_runtimes_promote_identical_bundle_across_all_environments(self):
        for runtime in ("prompt", "hosted", "harness"):
            ids = []
            for environment in ("dev", "test", "labprod"):
                candidate = self.create(runtime, environment)
                ids.append(candidate)
                self.approve(candidate)
                self.promote(candidate)
                self.assertEqual(self.lab.serving("contoso-" + runtime, environment)["candidate_id"], candidate)
            contexts = [self.lab.candidate(candidate)["context"] for candidate in ids]
            self.assertEqual(len({c["candidate_id"] for c in contexts}), 3)
            self.assertEqual(len({c["release_digest"] for c in contexts}), 1)
            self.assertEqual(len({c["binding_digest"] for c in contexts}), 3)

    def test_failed_or_missing_evaluation_preserves_serving_and_invalidates_old_pass(self):
        current = self.create()
        self.approve(current)
        self.promote(current)
        candidate = self.create(version="2")
        for report in (self.report(candidate, quality=0), self.report(candidate, unsafe=1)):
            self.approve(candidate)
            with self.assertRaisesRegex(LabError, "threshold"):
                self.lab.record_evaluation(candidate, report)
            self.assertIsNone(self.lab.candidate(candidate)["evaluation"])
            self.assertIsNone(self.lab.candidate(candidate)["approval"])
            with self.assertRaisesRegex(LabError, "passing evaluation"):
                self.promote(candidate)
            self.assertEqual(self.lab.serving("contoso-prompt", "dev")["candidate_id"], current)
        attempts = self.lab.history()
        self.assertTrue(any(row["outcome"] == "rejected" for row in attempts))
        self.assertEqual(len({row["attempt_id"] for row in attempts}), len(attempts))

    def test_quality_boundary_is_80_percent_without_relaxing_safety(self):
        candidate = self.create()
        self.lab.record_evaluation(candidate, self.report(candidate, quality=0.8))
        self.lab.approve(candidate, "synthetic-reviewer")
        self.assertIsNotNone(self.lab.candidate(candidate)["approval"])
        with self.assertRaisesRegex(LabError, "threshold failed: quality"):
            self.lab.record_evaluation(candidate, self.report(candidate, quality=0.799999))
        self.assertIsNone(self.lab.candidate(candidate)["approval"])
        with self.assertRaisesRegex(LabError, "threshold failed: unsafe"):
            self.lab.record_evaluation(candidate, self.report(candidate, quality=0.8, unsafe=0.01))
        self.assertIsNone(self.lab.candidate(candidate)["evaluation"])

    def test_runtime_change_cannot_bypass_existing_agent_memory_boundary(self):
        current = self.create()
        self.approve(current)
        self.promote(current)
        source = self.root / "harness2"
        manifest = read_json(source / "release.json")
        manifest["agent"] = "contoso-prompt"
        (source / "release.json").write_bytes(canonical(manifest))
        self.bundle_paths["harness", "2"] = artifacts.build(source, self.root / "bundles")
        candidate = self.create(runtime="harness", version="2")
        self.approve(candidate)
        with self.assertRaisesRegex(LabError, "separately named agent"):
            self.promote(candidate)
        self.assertEqual(self.lab.serving("contoso-prompt", "dev")["candidate_id"], current)

    def test_exact_context_missing_metrics_nonfinite_and_final_status_fail_closed(self):
        candidate = self.create()
        base = self.report(candidate)
        invalid = []
        for field in base["context"]:
            report = copy.deepcopy(base)
            report["context"][field] = "different"
            invalid.append(report)
        for value in (float("nan"), float("inf"), True, -1, 10 ** 1000):
            report = copy.deepcopy(base)
            report["metrics"]["cost_usd"] = value
            invalid.append(report)
        report = copy.deepcopy(base)
        del report["metrics"]["quality"]
        invalid.append(report)
        report = copy.deepcopy(base)
        report["status"] = "incomplete"
        invalid.append(report)
        report = copy.deepcopy(base)
        report["completed_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        invalid.append(report)
        for report in invalid:
            with self.assertRaises(LabError):
                self.lab.record_evaluation(candidate, report)
        self.assertEqual(self.lab.serving("contoso-prompt", "dev")["generation"], 0)

    def test_approval_is_invalidated_by_reevaluation_or_competing_promotion(self):
        first = self.create()
        second = self.create(version="2")
        self.approve(first)
        self.approve(second)
        self.promote(first)
        with self.assertRaisesRegex(LabError, "stale"):
            self.promote(second)
        self.lab.approve(second, "synthetic-reviewer")
        self.lab.record_evaluation(second, self.report(second))
        with self.assertRaisesRegex(LabError, "approval"):
            self.promote(second)

    def test_environment_cannot_skip_or_promote_different_upstream_release(self):
        candidate = self.create(environment="test")
        self.approve(candidate)
        with self.assertRaisesRegex(LabError, "Previous environment"):
            self.promote(candidate)
        dev = self.create(version="2")
        self.approve(dev)
        self.promote(dev)
        with self.assertRaisesRegex(LabError, "different release"):
            self.promote(candidate)

    def test_composite_rollback_and_component_retention(self):
        for runtime in ("prompt", "hosted", "harness"):
            first = self.create(runtime)
            self.approve(first)
            self.promote(first)
            second = self.create(runtime, version="2")
            self.approve(second)
            self.promote(second)
            self.approve(first)
            self.promote(first, rollback=True)
            old = self.lab.candidate(first)
            self.assertEqual(self.lab.serving("contoso-" + runtime, "dev")["candidate_id"], first)
            for name, digest in old["context"]["component_digests"].items():
                with self.assertRaisesRegex(LabError, "retained"):
                    self.lab.retire_component("dev", name, digest)
        reopened = ReleaseLab(self.root / "lab")
        self.assertEqual(reopened.history(), self.lab.history())

    def test_retirement_between_creation_and_promotion_is_rechecked(self):
        candidate = self.create()
        self.approve(candidate)
        digest = self.lab.candidate(candidate)["context"]["component_digests"]["contoso-tool"]
        self.lab.retire_component("dev", "contoso-tool", digest)
        with self.assertRaisesRegex(LabError, "retired"):
            self.promote(candidate)

    def test_denied_runtime_access_is_not_candidate_readiness(self):
        with self.assertRaisesRegex(LabError, "readiness/access"):
            self.create(readiness={"evidence_type": "simulated", "identity": "synthetic-runtime",
                                   "access": False, "status": "completed"})
        self.assertEqual(self.lab.history()[-1]["outcome"], "rejected")
        self.assertEqual(self.lab.serving("contoso-prompt", "dev")["generation"], 0)

    def test_expired_evaluation_and_unretained_rollback_fail_closed(self):
        candidate = self.create()
        report = self.report(candidate)
        with self.assertRaisesRegex(LabError, "stale"):
            evaluate(self.lab.candidate(candidate), report,
                     datetime.now(timezone.utc) + timedelta(hours=2))
        self.approve(candidate)
        with self.assertRaisesRegex(LabError, "not previously approved"):
            self.promote(candidate, rollback=True)

    def test_one_consumer_rollback_does_not_move_another(self):
        shared = self.create("harness")
        self.approve(shared)
        self.promote(shared)
        unchanged = self.lab.serving("contoso-harness", "dev")
        first = self.create()
        self.approve(first)
        self.promote(first)
        second = self.create(version="2")
        self.approve(second)
        self.promote(second)
        self.approve(first)
        self.promote(first, rollback=True)
        self.assertEqual(self.lab.serving("contoso-harness", "dev"), unchanged)
        self.assertEqual(self.lab.candidate(shared)["binding"]["components"]["contoso-knowledge"],
                         self.lab.candidate(first)["binding"]["components"]["contoso-knowledge"])

    def test_memory_binding_switch_requires_migration_evidence(self):
        first = self.create()
        self.approve(first)
        self.promote(first)
        path, digest = self.bundle_paths["prompt", "1"]
        bundle = artifacts.load(path, digest)
        binding, content, state = bindings.synthetic_records(bundle, "dev")
        binding["components"]["contoso-memory"]["resource"] = "synthetic://dev/other-store"
        candidate = self.lab.create(path, digest, binding, content, state, {
            "evidence_type": "simulated", "identity": "synthetic", "access": True, "status": "completed",
        })["candidate_id"]
        self.approve(candidate)
        with self.assertRaisesRegex(LabError, "verified migration"):
            self.promote(candidate)
        self.assertEqual(self.lab.serving("contoso-prompt", "dev")["candidate_id"], first)


if __name__ == "__main__":
    unittest.main()
