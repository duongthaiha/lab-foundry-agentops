import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path

from agentops import artifacts, bindings
from agentops.contracts import LabError, utc_now
from agentops.examples import write_example
from agentops.locks import resource_locks
from agentops.releases import ReleaseLab


def hold_lock(root, ready):
    with resource_locks(Path(root), ["dev/component/shared-knowledge"]):
        ready.set()
        time.sleep(30)


def competing_promotion(root, candidate, queue):
    try:
        result = ReleaseLab(Path(root)).promote(candidate, {"candidate_id": None, "generation": 0})
        queue.put(result["candidate_id"])
    except LabError:
        queue.put("rejected")


class LockTests(unittest.TestCase):
    def test_process_exclusion_environment_scope_and_crash_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            process = context.Process(target=hold_lock, args=(str(root), ready))
            process.start()
            try:
                self.assertTrue(ready.wait(10), "Lock holder failed to start")
                with self.assertRaisesRegex(LabError, "timeout"):
                    with resource_locks(root, ["dev/component/shared-knowledge"], timeout=0.05):
                        self.fail("Competing process acquired the held lock")
                with resource_locks(root, ["test/component/shared-knowledge"], timeout=0.05):
                    pass
                process.terminate()
                process.join(10)
                self.assertFalse(process.is_alive())
                with resource_locks(root, ["dev/component/shared-knowledge"], timeout=1):
                    pass
            finally:
                if process.is_alive():
                    process.terminate()
                process.join(10)
                process.close()

    def test_competing_promotions_cannot_both_pass_expected_serving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_example(root / "source", "prompt", "a" * 40)
            path, digest = artifacts.build(root / "source", root / "bundles")
            bundle = artifacts.load(path, digest)
            binding, content, state = bindings.synthetic_records(bundle, "dev")
            lab = ReleaseLab(root / "lab")
            ids = []
            for _ in range(2):
                candidate = lab.create(path, digest, binding, content, state, {
                    "evidence_type": "simulated", "identity": "synthetic", "access": True,
                    "status": "completed",
                })["candidate_id"]
                lab.record_evaluation(candidate, {
                    "evidence_type": "simulated", "status": "completed",
                    "context": lab.candidate(candidate)["context"], "completed_at": utc_now(),
                    "metrics": {"quality": 1, "unsafe": 0, "latency_ms": 1, "cost_usd": 0},
                })
                lab.approve(candidate, "synthetic")
                ids.append(candidate)
            context = multiprocessing.get_context("spawn")
            queue = context.Queue()
            processes = [context.Process(target=competing_promotion,
                                         args=(str(root / "lab"), candidate, queue)) for candidate in ids]
            try:
                for process in processes:
                    process.start()
                results = [queue.get(timeout=15) for _ in processes]
                self.assertEqual(results.count("rejected"), 1)
                self.assertEqual(lab.serving("contoso-prompt", "dev")["generation"], 1)
                for process in processes:
                    process.join(10)
                    self.assertEqual(process.exitcode, 0)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(10)
                    process.close()
                queue.close()
                queue.join_thread()
