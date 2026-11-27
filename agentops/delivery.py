"""Operator entry point for real dependency probes; native serving remains separately gated."""

from __future__ import annotations

import argparse
import copy
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import (
    ENVIRONMENTS, RUNTIMES, LabError, canonical, digest_value, fields, fingerprint,
    read_json, require, utc_now,
)
from .delivery_azure import BlobJournal, Foundry, ensure, project_shape
from .delivery_contracts import ANSWER_SCHEMA, TOOL_NAME, endpoint, load, release, save
from .delivery_evaluation import grade
from .delivery_knowledge import MCP_API, acquire_source, materialize, verify_knowledge
from .delivery_native import NativeDelivery, NativeRuntime

REPO = "duongthaiha/lab-foundry-agentops"
CONNECTION_API = "2025-10-01-preview"


def verify_source_revision(revision: str) -> None:
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "Full source revision required")
    root = Path(__file__).resolve().parent.parent
    for args, expected in ((["rev-parse", "HEAD"], revision),
                           (["status", "--porcelain", "--untracked-files=normal"], "")):
        try:
            result = subprocess.run(["git", "-C", str(root), *args],
                                    capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise LabError("Git source verification timed out") from exc
        require(result.returncode == 0, "Git source verification failed")
        require(result.stdout.strip() == expected,
                "Preparation requires the exact HEAD revision and a clean source checkout")


def gh(path: str) -> dict:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, "GitHub gate read failed")
    from .contracts import parse_json
    return parse_json(result.stdout)


def controls() -> dict:
    workflow = gh(f"repos/{REPO}/actions/workflows/platform.yml")
    flag = gh(f"repos/{REPO}/actions/variables/LIVE_PLATFORM_ENABLED")
    environments = {}
    for name in (*ENVIRONMENTS, "platform"):
        env = gh(f"repos/{REPO}/environments/{name}")
        policies = gh(f"repos/{REPO}/environments/{name}/deployment-branch-policies")
        reviewers = [rule for rule in env["protection_rules"] if rule["type"] == "required_reviewers"]
        environments[name] = {
            "reviewers_restored": any(
                item.get("reviewer", {}).get("login") == "duongthaiha"
                for rule in reviewers for item in rule.get("reviewers", [])),
            "main_only": policies["total_count"] == 1
            and policies["branch_policies"][0]["name"] == "main"
            and policies["branch_policies"][0]["type"] == "branch",
            "admin_bypass": env["can_admins_bypass"],
        }
    ready = workflow["state"] == "active" and flag["value"] == "true" and all(
        row["reviewers_restored"] and row["main_only"] and row["admin_bypass"] is False
        for row in environments.values())
    return {"live_ready": False, "platform_controls_ready": ready,
            "implementation_ready": False, "workflow": workflow["state"], "flag": flag["value"],
            "environments": environments, "checked_at": utc_now()}


def require_live_gate(run_id: str) -> dict:
    gate = controls()
    require(gate.get("platform_controls_ready", False),
            "Live controls are closed; no authentication, provisioning or probe performed")
    # Restoring platform gates alone cannot authorize this unfinished delivery path.
    raise LabError("Dependency execution is not enabled: runtime, cost, identity and safety preflight remains incomplete")


def validate_target(target: dict, environment: str):
    fields(target, {"environment", "project_endpoint", "project_resource_id", "search_endpoint",
                    "storage_endpoint", "tool_mcp_url", "tool_audience", "prices"})
    require(target["environment"] == environment, "Wrong target environment")
    endpoint(target["project_endpoint"], "services.ai.azure.com", project=True)
    endpoint(target["search_endpoint"], "search.windows.net")
    endpoint(target["storage_endpoint"], "blob.core.windows.net")
    require(re.fullmatch(
        r"/subscriptions/[0-9a-f-]{36}/resourceGroups/foudnry-agentops-lab-(dev|test|prod)"
        r"/providers/Microsoft\.CognitiveServices/accounts/[a-z0-9-]+/projects/[a-z0-9-]+",
        target["project_resource_id"]) is not None, "Project must be in the scoped lab groups")
    suffix = "prod" if environment == "labprod" else environment
    require(f"/resourceGroups/foudnry-agentops-lab-{suffix}/" in target["project_resource_id"],
            "Cross-environment project binding")
    tool = urlsplit(target["tool_mcp_url"])
    require(tool.scheme == "https" and tool.hostname and tool.hostname.endswith(".azurecontainerapps.io")
            and tool.path == "/mcp" and not tool.query and not tool.fragment
            and tool.username is None and tool.password is None and tool.port in (None, 443),
            "Expected a reviewed Entra-authenticated Container Apps MCP endpoint")
    require(re.fullmatch(r"api://[0-9a-f-]{36}", target["tool_audience"]) is not None,
            "Exact Entra tool audience required")


def connections(foundry, digest: str, knowledge: dict, *, create: bool = True) -> list[dict]:
    digest_value(digest, "release digest")
    target = foundry.target
    kb_url = target["search_endpoint"] + f"/knowledgebases/{knowledge['kb']}/mcp?api-version={MCP_API}"
    tools = []
    for label, url, audience, name in (
        ("knowledge-base", kb_url, "https://search.azure.com/", "knowledge_base_retrieve"),
        ("lab-tools", target["tool_mcp_url"] + f"/releases/{digest}", target["tool_audience"], TOOL_NAME),
    ):
        connection = f"{label}-{digest[:20]}"
        path = target["project_resource_id"] + f"/connections/{connection}?api-version={CONNECTION_API}"
        desired = {"properties": {
            "authType": "ProjectManagedIdentity", "category": "RemoteTool", "target": url,
            "isSharedToAll": True, "audience": audience, "metadata": {"ApiType": "Azure"},
        }}
        # Sent as documented, but the service persists false; access is governed by the project
        # identity and target RBAC, so this field is not part of the read-back contract.
        expected = {"properties": {key: value for key, value in desired["properties"].items()
                                   if key != "isSharedToAll"}}
        if create:
            ensure(foundry.arm, path, desired, expected)
        else:
            actual = foundry.arm.request("GET", path)
            require(project_shape(actual, expected) == expected, "Retained connection binding drift")
        # The service stores allowed_tools as this filter object; sending it keeps read-back exact.
        tools.append({"type": "mcp", "server_label": label, "server_url": url,
                      "allowed_tools": {"tool_names": [name]}, "require_approval": "never",
                      "project_connection_id": connection})
    return tools


def definition(bundle: dict, tools: list[dict], target: dict) -> dict:
    if bundle["runtime"] == "hosted":
        return {
            "kind": "hosted", "cpu": "1", "memory": "2Gi",
            "container_configuration": {"image": bundle["image"]},
            "protocol_versions": [{"protocol": "responses", "version": "2.0.0"}],
            "environment_variables": {
                "FOUNDRY_PROJECT_ENDPOINT": target["project_endpoint"],
                "FOUNDRY_MODEL_NAME": bundle["model"]["name"],
                "DELIVERY_INSTRUCTIONS": bundle["instructions"],
                "DELIVERY_TOOLS_JSON": canonical(tools).decode(),
                "DELIVERY_NEGATIVE_CONTROL": str(bundle["negative_control"]).lower(),
            },
        }
    result = {"kind": "prompt", "model": bundle["model"]["name"],
              "instructions": bundle["instructions"], "tools": tools}
    if bundle["runtime"] == "harness":
        result["harness"] = {"type": "microsoft_copilot_preview"}
        result["tools"] = [*tools, {
            "type": "microsoft_copilot_toolset_preview",
            "default_config": {"enabled": False}, "configs": [],
        }]
    if bundle["negative_control"]:
        result["tool_choice"] = "none"
        result["instructions"] = 'Return only {"announcement":"negative control"}. Do not call tools.'
    elif bundle["runtime"] == "prompt":
        # Ordinary prompt only; text.format support on the Copilot harness is unverified.
        result["text"] = {"format": {"type": "json_schema", "name": "lab_answer_v1", "strict": True,
                                     "schema": copy.deepcopy(ANSWER_SCHEMA)}}
    return result


def probe(bundle: dict, digest: str, foundry, journal, pages: list[dict], gate: dict) -> dict:
    """Execute real dependencies, not a claim of native serving promotion."""
    with journal.locked() as state:
        attempt = {"id": fingerprint({"release": digest, "at": utc_now()}), "started_at": utc_now(),
                   "release_digest": digest, "runtime": bundle["runtime"],
                   "environment": foundry.target["environment"], "gate": gate, "status": "started"}
        state["history"].append(attempt)
        journal.save(state)
        try:
            journal.check()
            knowledge = materialize(foundry, bundle["source"]["sha256"], pages)
            journal.check()
            tools = connections(foundry, digest, knowledge)
            desired = definition(bundle, tools, foundry.target)
            name = f"probe-{bundle['runtime']}-{digest[:20]}"
            before = foundry.get_agent(name)
            version = foundry.create_dependency_probe(name, desired, {"release_digest": digest, "purpose": "dependency-probe"})
            journal.check()
            verify_knowledge(foundry, knowledge, pages)
            started = time.monotonic()
            observed = foundry.invoke(name, version["version"], bundle["evaluation"]["questions"][0],
                                      bundle["runtime"], digest)
            result = grade(observed, foundry.target["environment"], knowledge["page_ids"],
                           foundry.target["prices"], time.monotonic() - started)
            journal.check()
            verify_knowledge(foundry, knowledge, pages)
            actual = foundry.get_version(name, version["version"])
            require(project_shape(actual["definition"], desired) == desired, "Definition drift after invocation")
            attempt.update({"status": "dependencies-observed", "completed_at": utc_now(),
                            "evaluation": result, "agent_name": name, "version": version["version"],
                            "binding_digest": fingerprint(foundry.target),
                            "definition_digest": fingerprint(desired),
                            "knowledge": knowledge, "existing_probe": before is not None,
                            "native_serving_validated": False, "memory_validated": False})
            state["candidates"][digest] = attempt
            journal.save(state)
            return attempt
        except Exception as exc:
            attempt.update({"status": "failed", "completed_at": utc_now(), "error_type": type(exc).__name__,
                            "native_serving_validated": False})
            journal.save(state)
            raise


def matrix() -> dict:
    return {
        "evidence_type": "implementation-status", "live_validation": False,
        "tracks": {runtime: {
            "iq_mcp": "adapter-implemented-not-live-validated",
            "distinct_mcp_tool": "adapter-implemented-not-live-validated",
            "toolbox_lifecycle": "sdk-contract-tested-not-runtime-integrated",
            "native_controller": "contract-tested-not-wired-to-live-operator",
            "native_consumer": "sdk-wire-tested-protected-command-disabled",
            "native_serving_cutover": "unfulfilled",
            "native_rollback": "unfulfilled",
            "memory": "unsupported-no-substitute" if runtime == "harness" else "unfulfilled",
            "memory_api": "unsupported-no-substitute" if runtime == "harness" else "contract-tested-not-runtime-integrated",
        } for runtime in RUNTIMES},
        "cells": [{"runtime": runtime, "environment": environment, "live_status": "not-run"}
                  for runtime in RUNTIMES for environment in ENVIRONMENTS],
        "prompt_pipeline": {
            "entrypoint": "agentops.delivery_pipeline", "implemented": True, "live_validation": False,
            "workflow": "promote.yml", "rollback_workflow": "rollback.yml",
            "environments": list(ENVIRONMENTS),
            "boundary": "Protected ordinary-Prompt path; not hosted/harness or the legacy probe gate.",
        },
        "boundary": "Dependency probes do not satisfy the native-serving acceptance criterion.",
    }


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Download reviewed PDF locally and build portable releases")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--source-revision", required=True)
    prepare.add_argument("--runtime", choices=RUNTIMES, required=True)
    prepare.add_argument("--image")
    prepare.add_argument("--negative", action="store_true")
    commands.add_parser("readiness", help="Read GitHub controls only; never opens the live gate")
    commands.add_parser("matrix")
    for name, help_text in (
        ("probe", "Protected real IQ/MCP dependency probe, not promotion"),
        ("verify-serving", "Protected native consumer diagnostic, not release validation"),
    ):
        action = commands.add_parser(name, help=help_text)
        action.add_argument("--bundle", type=Path, required=True)
        action.add_argument("--digest", required=True)
        action.add_argument("--target", type=Path, required=True)
        action.add_argument("--environment", choices=ENVIRONMENTS, required=True)
        if name == "probe":
            action.add_argument("--sources", type=Path, required=True)
        action.add_argument("--approved-run-id", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "matrix":
            result = matrix()
        elif args.command == "readiness":
            result = controls()
        elif args.command == "prepare":
            require(args.output.resolve().is_relative_to((Path.cwd() / ".lab").resolve()),
                    "Keep downloaded publisher content inside ignored .lab")
            verify_source_revision(args.source_revision)
            source_hash, pages = acquire_source(args.output / "sources")
            value = release(args.runtime, args.source_revision, source_hash, image=args.image,
                            negative=args.negative)
            path, digest = save(value, args.output / "releases")
            result = {"evidence_type": "local-preparation", "bundle": str(path), "digest": digest,
                      "pdf_sha256": source_hash, "page_count": len(pages),
                      "source_checkout_verified": True, "live_validation": False}
        else:
            gate = require_live_gate(args.approved_run_id)
            value = load(args.bundle, args.digest)
            target = read_json(args.target)
            validate_target(target, args.environment)
            from azure.identity import AzureCliCredential
            with AzureCliCredential() as credential:
                foundry = Foundry(target, credential)
                try:
                    journal = BlobJournal(target["storage_endpoint"], credential)
                    if args.command == "verify-serving":
                        result = NativeDelivery(
                            NativeRuntime(foundry, journal.check), journal, None, args.environment,
                        ).verify_serving(value, args.digest)
                    else:
                        _, pages = acquire_source(args.sources, value["source"]["sha256"])
                        result = probe(value, args.digest, foundry, journal, pages, gate)
                finally:
                    foundry.close()
        sys.stdout.write(canonical(result).decode())
        return 0
    except (LabError, OSError, KeyError, ValueError) as exc:
        sys.stderr.write(canonical({"status": "error", "reason": str(exc)}).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
