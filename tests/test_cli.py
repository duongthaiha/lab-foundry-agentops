import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentops.contracts import read_json
from agentops.simulation import PLACEHOLDER_APPROVER

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, "-W", "error::ResourceWarning", "-m", "agentops", *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=60)

    def test_live_mode_fails_without_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "untouched"
            result = self.cli("--mode", "live", "--state", str(state), "history")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Live operations are unavailable", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse(state.exists())

    def test_placeholder_cannot_authorize_live_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "untouched"
            result = self.cli("--mode", "live", "--state", str(state), "approve",
                              "--candidate", "synthetic-candidate", "--approver", PLACEHOLDER_APPROVER)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Live operations are unavailable", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse(state.exists())

    def test_replayable_three_runtime_demo_and_persistent_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo"
            result = self.cli("--mode", "simulated", "demo", "--output", str(output),
                              "--source-revision", "a" * 40)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)["result"]
            self.assertFalse(summary["live_validation"])
            self.assertFalse(summary["live_authorization"])
            self.assertEqual(summary["approval_mode"], "placeholder")
            self.assertEqual(summary["placeholder_approvals"], 27)
            self.assertEqual(summary["failed_evaluation_approval_blocks"], 9)
            self.assertEqual(summary["runtimes"], 3)
            report = read_json(output / "report.json")
            self.assertEqual(set(report["runtimes"]), {"prompt", "hosted", "harness"})
            self.assertEqual(len(report["memory"]), 6)
            self.assertEqual(report["harness_memory"], "unsupported-no-substitute")
            approvals = [attempt for attempt in report["attempts"]
                         if attempt["operation"] == "approve" and attempt["outcome"] == "succeeded"]
            self.assertEqual(len(approvals), summary["placeholder_approvals"])
            self.assertTrue(all(attempt["details"]["approval"]["approver"] == PLACEHOLDER_APPROVER
                                for attempt in approvals))
            self.assertGreaterEqual(summary["rejected_attempts"], 12)
            for runtime in report["runtimes"].values():
                for release in runtime["releases"].values():
                    self.assertEqual(set(release["environments"]), {"dev", "test", "labprod"})
                    for environment in release["environments"].values():
                        context = environment["candidate"]["context"]
                        self.assertEqual(context["release_digest"], release["digest"])
                        self.assertEqual(environment["creation"]["serving_before"],
                                         environment["creation"]["serving_after"])
                self.assertEqual(set(runtime["rollback"]), {"dev", "test", "labprod"})
            history = self.cli("--mode", "simulated", "--state", str(output / "state"), "history")
            self.assertEqual(history.returncode, 0, history.stderr)
            self.assertEqual(json.loads(history.stdout)["result"], report["attempts"])
            original = (output / "report.json").read_bytes()
            rerun = self.cli("--mode", "simulated", "demo", "--output", str(output),
                             "--source-revision", "a" * 40)
            self.assertNotEqual(rerun.returncode, 0)
            self.assertEqual(original, (output / "report.json").read_bytes())
