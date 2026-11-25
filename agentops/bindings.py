"""Resolve only explicit synthetic environment bindings; never an Azure fallback."""

from typing import Any
from urllib.parse import urlsplit

from .artifacts import references
from .contracts import ENVIRONMENTS, LabError, evidence_record, fields, fingerprint, require, text


def _resource(value: Any, environment: str) -> None:
    try:
        resource = urlsplit(text(value, "synthetic resource"))
    except ValueError as exc:
        raise LabError("Invalid synthetic resource URI") from exc
    require(resource.scheme == "synthetic" and resource.netloc == environment and
            resource.path.startswith("/") and len(resource.path) > 1 and
            not resource.query and not resource.fragment and
            all(part not in (".", "..") for part in resource.path.split("/")) and
            "%" not in resource.path and "\\" not in resource.path,
            "Cross-environment or invalid synthetic binding")


def validate(bundle: dict[str, Any], binding: Any, content: Any, state: Any) -> dict[str, Any]:
    fields(binding, {"schema_version", "environment", "evidence_type", "model_deployment", "components"})
    require(type(binding["schema_version"]) is int and binding["schema_version"] == 1,
            "Unsupported binding schema")
    require(binding["environment"] in ENVIRONMENTS, "Unknown environment")
    require(binding["evidence_type"] == "simulated", "Live bindings are not implemented")
    environment = binding["environment"]
    _resource(binding["model_deployment"], environment)
    refs = references(bundle)
    require(isinstance(binding["components"], dict) and
            binding["components"].keys() == refs["components"].keys(), "Component binding set mismatch")
    for name, reference in refs["components"].items():
        value = binding["components"][name]
        fields(value, {"resource", "contract_digest"})
        require(value["contract_digest"] == reference["digest"], "Component contract mismatch")
        _resource(value["resource"], environment)
    evidence_record(content, "content")
    evidence_record(state, "state")
    knowledge = {name for name, ref in refs["components"].items() if ref["kind"] == "knowledge"}
    memory = {name for name, ref in refs["components"].items() if ref["kind"] == "memory-policy"}
    require(content["snapshots"].keys() == knowledge, "Knowledge content snapshot set mismatch")
    require(state["snapshots"].keys() == memory, "Memory fixture snapshot set mismatch")
    return {
        "binding_digest": fingerprint(binding), "content_digest": fingerprint(content),
        "state_digest": fingerprint(state), **refs["evaluation"],
        "component_digests": {name: ref["digest"] for name, ref in refs["components"].items()},
    }


def synthetic_records(bundle: dict[str, Any], environment: str) -> tuple[dict, dict, dict]:
    refs = references(bundle)["components"]
    binding = {
        "schema_version": 1, "evidence_type": "simulated", "environment": environment,
        "model_deployment": f"synthetic://{environment}/models/contoso",
        "components": {name: {
            "resource": f"synthetic://{environment}/{name}/{ref['digest']}",
            "contract_digest": ref["digest"],
        } for name, ref in refs.items()},
    }
    content = {"category": "content", "evidence_type": "simulated", "snapshots": {
        name: fingerprint({"environment": environment, "content": ref["digest"]})
        for name, ref in refs.items() if ref["kind"] == "knowledge"
    }}
    state = {"category": "state", "evidence_type": "simulated", "snapshots": {
        name: fingerprint({"environment": environment, "fixture": "isolated-evaluation", "consumer": bundle["manifest"]["agent"]})
        for name, ref in refs.items() if ref["kind"] == "memory-policy"
    }}
    return binding, content, state
