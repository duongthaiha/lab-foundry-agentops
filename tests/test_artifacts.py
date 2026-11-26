import copy
import tempfile
import unittest
from pathlib import Path

from agentops import artifacts, bindings
from agentops.contracts import LabError, canonical, parse_json, read_json
from agentops.examples import write_example


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        write_example(self.source, "prompt", "a" * 40)

    def build(self):
        return artifacts.build(self.source, self.root / "bundles")

    def change(self, path, mutate):
        value = read_json(self.source / path)
        mutate(value)
        (self.source / path).write_bytes(canonical(value))

    def test_deterministic_bundle_and_independent_change_digests(self):
        path, original = self.build()
        self.assertEqual((path, original), self.build())
        for file, key in (("agent.json", "instructions"), ("tool.json", "version"),
                          ("knowledge.json", "version"), ("memory.json", "version")):
            before = (self.source / file).read_bytes()
            self.change(file, lambda value: value.update({key: "changed"}))
            self.assertNotEqual(original, self.build()[1])
            (self.source / file).write_bytes(before)
        self.assertEqual(original, self.build()[1])

    def test_tampered_bundle_rejected(self):
        path, digest = self.build()
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(LabError, "digest mismatch"):
            artifacts.load(path, digest)

    def test_unsafe_paths_and_duplicate_keys_rejected(self):
        for path in ("../escape.json", "C:/escape.json", "/root.json", "a\\b.json",
                     "a/../b.json", "CON.json", "a./b.json", "a//b.json"):
            with self.subTest(path=path), self.assertRaises(LabError):
                artifacts.safe_path(path)
        with self.assertRaisesRegex(LabError, "Duplicate"):
            parse_json('{"a":1,"a":2}')
        with self.assertRaises(LabError):
            parse_json('{"a":NaN}')

    def test_nonportable_contract_rejected(self):
        self.change("tool.json", lambda value: value["configuration"].update({"endpoint": "not-portable"}))
        with self.assertRaisesRegex(LabError, "portable"):
            self.build()

    def test_all_runtime_contracts_and_harness_memory_boundary(self):
        for runtime in ("hosted", "harness"):
            source = self.root / runtime
            write_example(source, runtime, "a" * 40)
            path, digest = artifacts.build(source, self.root / "bundles")
            bundle = artifacts.load(path, digest)
            binding, content, state = bindings.synthetic_records(bundle, "dev")
            bindings.validate(bundle, binding, content, state)
            if runtime == "harness":
                definition = read_json(source / "agent.json")
                definition["memory"] = "custom-substitute"
                (source / "agent.json").write_bytes(canonical(definition))
                with self.assertRaisesRegex(LabError, "unsupported"):
                    artifacts.build(source, self.root / "bundles")

    def test_explicit_binding_scope_and_separate_content_state_evidence(self):
        path, digest = self.build()
        bundle = artifacts.load(path, digest)
        binding, content, state = bindings.synthetic_records(bundle, "dev")
        before = bindings.validate(bundle, binding, content, state)
        content["snapshots"]["contoso-knowledge"] = "b" * 64
        after = bindings.validate(bundle, binding, content, state)
        self.assertEqual(before["binding_digest"], after["binding_digest"])
        self.assertNotEqual(before["content_digest"], after["content_digest"])
        self.assertEqual(digest, self.build()[1])
        invalid = copy.deepcopy(binding)
        invalid["components"]["contoso-tool"]["resource"] = "synthetic://test/tool"
        with self.assertRaisesRegex(LabError, "Cross-environment"):
            bindings.validate(bundle, invalid, content, state)
        invalid = copy.deepcopy(binding)
        invalid["model_deployment"] = "synthetic://labprod/models/contoso"
        with self.assertRaisesRegex(LabError, "Cross-environment"):
            bindings.validate(bundle, invalid, content, state)
        invalid = copy.deepcopy(binding)
        del invalid["components"]["contoso-tool"]
        with self.assertRaises(LabError):
            bindings.validate(bundle, invalid, content, state)
        invalid = copy.deepcopy(binding)
        invalid["evidence_type"] = "live"
        with self.assertRaisesRegex(LabError, "not implemented"):
            bindings.validate(bundle, invalid, content, state)


if __name__ == "__main__":
    unittest.main()
