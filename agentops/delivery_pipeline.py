"""Protected ordinary-Prompt delivery: immutable dev -> test -> labprod and retained rollback."""

from __future__ import annotations

import argparse
import copy
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts import (
    ENVIRONMENTS, LabError, canonical, digest_value, fields, finite, fingerprint,
    identifier, instant, parse_json, require, utc_now,
)
from .delivery import REPO, connections, definition, gh, validate_target, verify_source_revision
from .delivery_azure import BlobJournal, Foundry, project_shape
from .delivery_contracts import NATIVE_EVALUATION_VERSION, endpoint, load, release, validate
from .delivery_dev import (
    CheckedHTTP, inspect_environment, judge_response, measured_cost, validate_binding, verify_ci_identity,
)
from .delivery_evaluation import grade
from .delivery_knowledge import acquire_source, materialize, verify_knowledge
from .delivery_native import NativeDelivery, NativeRuntime

WORKFLOWS = {"promote": "promote.yml", "rollback": "rollback.yml"}
RESERVATION_USD = 0.50
SETTLED = {"promoted", "rejected", "rolled-back", "failed-before-mutation", "failed-before-cutover"}
BASELINE = {
    "kind": "prompt", "model": "gpt-5-mini", "tools": [], "tool_choice": "none",
    "instructions": "No evaluated release has been promoted. Reply only: AgentOps lab is not ready.",
}


def validate_configuration(config: dict, environment: str) -> None:
    fields(config, {"current", "upstream", "journal_endpoint", "journal_resource_id"})
    current = validate_binding(config["current"], environment)
    endpoint(config["journal_endpoint"], "blob.core.windows.net")
    prefix = (f"/subscriptions/{current['subscription_id']}/resourceGroups/foudnry-agentops-lab-dev/"
              "providers/Microsoft.Storage/storageAccounts/")
    require(re.fullmatch(re.escape(prefix) + r"[a-z0-9]{3,24}", config["journal_resource_id"]) is not None,
            "All environments must use the reviewed dev coordination storage")
    require(config["journal_endpoint"] == (
        "https://" + config["journal_resource_id"].rsplit("/", 1)[1] + ".blob.core.windows.net"),
        "Journal endpoint and resource differ")
    index = ENVIRONMENTS.index(environment)
    if not index:
        require(config["upstream"] is None
                and config["journal_endpoint"] == current["target"]["storage_endpoint"],
                "Dev must own the shared journal and have no upstream")
    else:
        validate_target(config["upstream"], ENVIRONMENTS[index - 1])
        require(config["upstream"]["project_resource_id"].startswith(
            f"/subscriptions/{current['subscription_id']}/"), "Upstream subscription differs")
        require(config["upstream"]["project_endpoint"] != current["target"]["project_endpoint"],
                "Environments cannot share a Foundry project")


def authorize(environ: dict, environment: str, action: str, digest: str,
              read=gh, now: datetime | None = None) -> tuple[dict, dict]:
    """Local environment spoofing is insufficient: verify GitHub run, protections and Entra separately."""
    now = now or datetime.now(timezone.utc)
    require(environment in ENVIRONMENTS and action in WORKFLOWS, "Unsupported delivery operation")
    require(environ.get("LIVE_DELIVERY_ENABLED") == "true", "Native delivery is disabled; no Azure login")
    path = ".github/workflows/" + WORKFLOWS[action]
    require(environ.get("GITHUB_ACTIONS") == "true" and environ.get("GITHUB_REPOSITORY") == REPO
            and environ.get("GITHUB_REF") == "refs/heads/main"
            and environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and environ.get("GITHUB_WORKFLOW_REF") == f"{REPO}/{path}@refs/heads/main",
            "Only the protected main delivery workflow may execute")
    digest_value(digest, "release digest")
    policy = parse_json(environ.get("DELIVERY_POLICY", ""))
    config = parse_json(environ.get("DELIVERY_BINDING", ""))
    fields(policy, {"mode", "id", "source_revision", "binding_digest", "release_digests", "actions",
                    "valid_from", "expires_at", "price_checked_at",
                    "estimated_monthly_usd", "max_operations", "allow_bootstrap"})
    require(policy["mode"] == "prompt-delivery-v1", "Wrong native delivery policy")
    identifier(policy["id"], "policy ID")
    require(re.fullmatch(r"[0-9a-f]{40}", policy["source_revision"]) is not None, "Reviewed operator SHA required")
    require(isinstance(policy["release_digests"], list) and 1 <= len(policy["release_digests"]) <= 10,
            "Explicit release allowlist required")
    for value in policy["release_digests"]:
        digest_value(value, "allowed release")
    require(digest in policy["release_digests"], "Release was not reviewed")
    require(isinstance(policy["actions"], list) and policy["actions"]
            and set(policy["actions"]) <= set(WORKFLOWS) and action in policy["actions"],
            "Operation was not authorized")
    start, end = instant(policy["valid_from"]), instant(policy["expires_at"])
    require(start <= now < end and end - start <= timedelta(days=7), "Delivery policy is expired or too long")
    require(timedelta(0) <= now - instant(policy["price_checked_at"]) <= timedelta(days=7),
            "Price observation is stale")
    require(0 < finite(policy["estimated_monthly_usd"], "monthly estimate") <= 500,
            "Original $500 monthly estimate bound remains in force")
    require(type(policy["max_operations"]) is int and 1 <= policy["max_operations"] <= 10
            and type(policy["allow_bootstrap"]) is bool, "Invalid attempt or bootstrap allowance")
    require(fingerprint(config) == policy["binding_digest"], "Reviewed environment binding changed")
    validate_configuration(config, environment)
    run_id, attempt = environ.get("GITHUB_RUN_ID", ""), environ.get("GITHUB_RUN_ATTEMPT", "")
    require(run_id.isdigit() and attempt.isdigit(), "GitHub run identity required")
    root = f"repos/{REPO}"
    run = read(f"{root}/actions/runs/{run_id}")
    workflow = read(f"{root}/actions/workflows/{WORKFLOWS[action]}")
    main = read(f"{root}/git/ref/heads/main")
    require(workflow["state"] == "active" and workflow["id"] == run["workflow_id"]
            and run["path"] == path and run["head_branch"] == "main" and run["event"] == "workflow_dispatch"
            and run["status"] == "in_progress" and run["run_attempt"] == int(attempt)
            and run["head_sha"] == environ.get("GITHUB_SHA") == policy["source_revision"] == main["object"]["sha"],
            "Not the reviewed current-main workflow run")
    protected = read(f"{root}/environments/{environment}")
    branches = read(f"{root}/environments/{environment}/deployment-branch-policies")
    require(protected["can_admins_bypass"] is False
            and protected["deployment_branch_policy"] == {
                "protected_branches": False, "custom_branch_policies": True}
            and branches["total_count"] == 1 and branches["branch_policies"][0]["name"] == "main"
            and branches["branch_policies"][0]["type"] == "branch",
            "Environment must be main-only with administrator bypass disabled")
    require(any(item.get("reviewer", {}).get("login") == "duongthaiha"
                for rule in protected["protection_rules"] if rule["type"] == "required_reviewers"
                for item in rule.get("reviewers", [])), "Delivery requires the owner's environment review gate")
    approvals = read(f"{root}/actions/runs/{run_id}/approvals")
    require(any(row.get("state") == "approved" and row.get("user", {}).get("login") == "duongthaiha"
                and any(env.get("name") == environment for env in row.get("environments", []))
                for row in approvals), "Environment operation has no recorded human approval")
    return policy, config


class LockedJournal:
    """Reuse one remote lease across dependency reconciliation, evaluation and cutover."""

    def __init__(self, journal, state: dict, reauthorize):
        self.journal, self.state, self.reauthorize = journal, state, reauthorize

    @contextmanager
    def locked(self):
        self.check()
        yield self.state

    def check(self):
        self.reauthorize()
        self.journal.check()

    def save(self, state):
        self.check()
        self.journal.save(state)


class MeteredRuntime(NativeRuntime):
    def __init__(self, foundry, check, charge):
        super().__init__(foundry, check)
        self.charge = charge

    def invoke_version(self, *args, **kwargs):
        result = super().invoke_version(*args, **kwargs)
        response = result["response"]
        self.charge(response, sum(row["type"] == "mcp_call" for row in response["output"]))
        return result

    def invoke_serving(self, *args, **kwargs):
        result = super().invoke_serving(*args, **kwargs)
        self.charge(result, result["tool_call_count"])
        return result


def evaluate_case(foundry, bundle, observation, pages, knowledge, caller, check, charge) -> dict:
    """Only authenticated, subject-bound measured evaluation can produce a passing gate."""
    try:
        structural = grade(observation, foundry.target["environment"], knowledge["page_ids"],
                           foundry.target["prices"], observation["latency_seconds"],
                           max_case_usd=bundle["evaluation"]["max_case_usd"])
        require(all(structural["checks"].values()), "Incomplete structural answer")
        auth = structural["authenticated_tool_calls"]
        tool_calls = [row for row in structural["tool_evidence"] if row["server_label"] == "lab-tools"]
        require(auth and len(auth) == len(tool_calls)
                and all(row.get("release_digest") == observation["release_digest"]
                        and row["principal_digest"] == caller for row in auth),
                "Runtime tool identity or release binding differs")
        semantic = judge_response(foundry, bundle, observation, pages, structural, check,
                                  max_case_usd=bundle["evaluation"]["max_case_usd"], charge=charge)
        require(semantic["subject_digest"] == fingerprint(observation["response"]),
                "Evaluator subject differs")
        return {"full_gate_passed": True, "structural": structural, "semantic": semantic,
                "rubric": NATIVE_EVALUATION_VERSION}
    except LabError as exc:
        # Invalid observations/grades reject the candidate. Transport/SDK errors propagate as uncertainty.
        return {"full_gate_passed": False, "reason": str(exc), "rubric": NATIVE_EVALUATION_VERSION}


class ContextInspector:
    def __init__(self, foundry, binding: dict, definitions: dict):
        self.foundry, self.binding = foundry, binding
        self.definitions = definitions

    def __call__(self, desired: dict) -> dict:
        matches = []
        for row in self.definitions.values():
            expected = row["definition"]
            try:
                matched = project_shape(desired, expected) == expected
            except LabError:
                matched = False
            if matched:
                matches.append(row)
        require(len(matches) == 1, "Unregistered or ambiguous retained definition")
        row = matches[0]
        current = self.binding
        caller = inspect_environment(self.foundry, current, current["target"]["environment"])
        target = {key: value for key, value in current["target"].items() if key != "prices"}
        if row["knowledge"] is None:
            require(project_shape(desired, BASELINE) == BASELINE, "Bootstrap baseline changed")
            content = fingerprint({"content": None})
        else:
            bundle, knowledge = row["bundle"], row["knowledge"]
            require(current["tool_image"].endswith("@sha256:" + bundle["tool_image_sha256"]),
                    "Retained MCP image differs from its release")
            verify_knowledge(self.foundry, knowledge)
            tools = connections(self.foundry, fingerprint(bundle), knowledge, create=False)
            expected = definition(bundle, tools, current["target"])
            require(project_shape(desired, expected) == expected, "Release dependency binding changed")
            content = knowledge["content_watermark"]
        return {
            "components_digest": fingerprint({"definition": row["definition"], "target": target,
                                              "tool_image": current["tool_image"]}),
            "content_digest": content, "identity_digest": caller,
            "state_digest": fingerprint({"memory": "not-attached", "mutable_dependencies": []}),
            "policy_digest": fingerprint({"model": "gpt-5-mini-2025-08-07", "policy": "Microsoft.DefaultV2",
                                          "rubric": NATIVE_EVALUATION_VERSION}),
        }


def bootstrap(foundry, bundle: dict, policy: dict, definitions: dict, owned_agents: dict,
              view: LockedJournal) -> None:
    name = bundle["agent"]
    environment = foundry.target["environment"]
    if foundry.get_agent(name) is not None:
        require(owned_agents.get(environment) == name and definitions,
                "Existing agent is not owned by this delivery journal")
        return
    require(environment not in owned_agents, "Owned agent disappeared; reconcile instead of replacing it")
    require(policy["allow_bootstrap"], "A new agent needs explicit baseline bootstrap authorization")
    view.check()
    version = foundry.client.agents.create_version(name, body={
        "definition": copy.deepcopy(BASELINE), "metadata": {"purpose": "prompt-pipeline-baseline-v1"},
        "draft": False,
    }).as_dict()
    version = NativeRuntime(foundry, view.check).wait_active(name, version)
    require(version["status"] == "active" and not version.get("draft", False)
            and project_shape(version["definition"], BASELINE) == BASELINE,
            "Baseline is not active or differs; reconcile instead of recreating")
    definitions[fingerprint(BASELINE)] = {"definition": copy.deepcopy(BASELINE), "knowledge": None}
    owned_agents[environment] = name
    view.save(view.state)
    view.check()
    foundry.client.agents.update_details(name, body={"agent_endpoint": {"version_selector": {
        "version_selection_rules": [{"type": "FixedRatio", "agent_version": version["version"],
                                     "traffic_percentage": 100}]}}})
    require(NativeRuntime(foundry, view.check).snapshot(name)["version"] == version["version"],
            "Bootstrap selector read-back differs")


def execute(foundry, journal, policy: dict, config: dict, bundle: dict, digest: str,
            run_key: str, action: str, reauthorize, source_loader, upstream_check) -> dict:
    validate(bundle)
    require(bundle["runtime"] == "prompt" and fingerprint(bundle) == digest
            and bundle["evaluation"]["version"] == NATIVE_EVALUATION_VERSION,
            "Only the exact current native Prompt evaluation contract is supported")
    require(digest in policy["release_digests"] and action in policy["actions"], "Unreviewed operation")
    binding = config["current"]
    require("tool_image_sha256" in bundle
            and binding["tool_image"].endswith("@sha256:" + bundle["tool_image_sha256"]),
            "MCP image must match the immutable composite release")
    require(foundry.target == binding["target"], "Authenticated target differs")
    environment = foundry.target["environment"]
    validate_configuration(config, environment)
    with journal.locked() as state:
        view = LockedJournal(journal, state, reauthorize)
        view.check()
        ledger = state.setdefault("delivery_pipeline", {"attempts": {}, "policies": {}, "definitions": {}})
        attempts = ledger["attempts"]
        pending = [row for row in attempts.values() if row["status"] not in SETTLED]
        require(not pending or (action == "rollback" and all(
            row["environment"] == environment and row["action"] in ("promote", "rollback")
            and row["release_digest"] == digest for row in pending)),
            "An uncertain operation needs reconciliation or its exact rollback")
        require(run_key not in attempts, "Attempt already exists; never replay uncertain usage")
        require(len(attempts) < policy["max_operations"], "Lifetime operation allowance exhausted")
        prior_policy = ledger["policies"].setdefault(policy["id"], fingerprint(policy))
        require(prior_policy == fingerprint(policy), "Policy ID cannot be reused with different bounds")
        attempt = {"status": "reserved", "environment": environment, "action": action,
                   "release_digest": digest, "binding_digest": fingerprint(config),
                   "reserved_usd": RESERVATION_USD, "measured_upper_bound_usd": 0,
                   "started_at": utc_now(), "run_key": run_key, "full_gate_passed": False,
                   "mutation_started": False}
        attempts[run_key] = attempt
        view.save(state)
        mutation_started = False

        def charge(response, tool_calls):
            cost = measured_cost(response, foundry.target["prices"])
            cost += tool_calls * foundry.target["prices"]["tool_call_upper_bound_usd"]
            cost += foundry.target["prices"]["safety_call_upper_bound_usd"]
            attempt["measured_upper_bound_usd"] += cost
            view.save(state)
            require(0 <= tool_calls <= 2, "Measured request exceeded its tool-call bound")
            require(attempt["measured_upper_bound_usd"] <= RESERVATION_USD, "Operation reservation exceeded")

        original_arm, original_search = foundry.arm, foundry.search
        foundry.arm, foundry.search = CheckedHTTP(original_arm, view.check), CheckedHTTP(original_search, view.check)
        try:
            caller = inspect_environment(foundry, binding, environment)
            storage = foundry.arm.request("GET", config["journal_resource_id"] + "?api-version=2023-05-01")
            props = storage["properties"]
            require(props["primaryEndpoints"]["blob"].rstrip("/") == config["journal_endpoint"]
                    and props["allowSharedKeyAccess"] is False and props["allowBlobPublicAccess"] is False
                    and props["supportsHttpsTrafficOnly"] is True and props["minimumTlsVersion"] == "TLS1_2",
                    "Shared journal storage ownership/authentication drift")
            definitions = ledger["definitions"].setdefault(environment, {})
            inspector = ContextInspector(foundry, binding, definitions)
            runtime = MeteredRuntime(foundry, view.check, charge)
            attempt["safe_before"] = (
                runtime.snapshot(bundle["agent"]) if foundry.get_agent(bundle["agent"]) is not None else None)
            view.save(state)
            delivery = NativeDelivery(runtime, view, inspector, environment)
            if action == "promote":
                native = state.get("native", {}).get(environment, {})
                serving = native.get("serving", {}).get(bundle["agent"])
                if serving and serving["release_digest"] == digest:
                    require(runtime.snapshot(bundle["agent"]) == serving["after"], "Previously promoted route drift")
                    candidate = native["candidates"][digest]
                    require(candidate["passed"] is True and inspector(candidate["definition"]) == candidate["context"],
                            "Previously promoted context drift")
                    actual = foundry.get_version(bundle["agent"], serving["after"]["version"])
                    require(project_shape(actual["definition"], candidate["definition"]) == candidate["definition"]
                            and actual.get("metadata", {}).get("release_digest") == digest,
                            "Previously promoted version drift")
                    delivery.verify_serving(bundle, digest)
                    attempt.update({"status": "promoted", "full_gate_passed": True, "idempotent": True,
                                    "before": serving["after"], "after": serving["after"],
                                    "completed_at": utc_now(), "evidence_type": "live-native-delivery"})
                    view.save(state)
                    return attempt
                pages = source_loader(bundle["source"]["sha256"])
                mutation_started = True
                attempt.update({"mutation_started": True, "phase": "materializing"})
                view.save(state)
                knowledge = materialize(foundry, bundle["source"]["sha256"], pages)
                tools = connections(foundry, digest, knowledge)
                desired = definition(bundle, tools, foundry.target)
                bootstrap(foundry, bundle, policy, definitions, ledger.setdefault("agents", {}), view)
                if attempt["safe_before"] is None:
                    attempt["safe_before"] = runtime.snapshot(bundle["agent"])
                    view.save(state)
                definitions[fingerprint(desired)] = {
                    "definition": desired, "knowledge": knowledge, "bundle": bundle,
                }
                view.save(state)
                result = delivery.evaluate(bundle, digest, desired, lambda item: evaluate_case(
                    foundry, bundle, item, pages, knowledge, caller, view.check, charge))
                if result["passed"]:
                    result = delivery.promote(digest, upstream_check)
                    attempt.update({"status": "promoted", "full_gate_passed": True,
                                    "before": result["before"], "after": result["after"]})
                else:
                    attempt.update({"status": "rejected", "before": result["before"], "after": result["after"]})
            else:
                retained = state.get("native", {}).get(environment, {}).get("retained", {}).get(bundle["agent"])
                require(retained and retained["release_digest"] == digest,
                        "Rollback must name the exact current release, not a stale or arbitrary version")
                require(retained["previous_receipt"] is not None, "No previously evaluated release to restore")
                mutation_started = True
                attempt.update({"mutation_started": True, "phase": "rollback"})
                view.save(state)
                result = delivery.rollback(bundle["agent"])
                attempt.update({"status": "rolled-back", "before": result["before"], "after": result["after"],
                                "restored_release_digest": result["restored_release_digest"]})
                for row in pending:
                    row.update({"recovered_from": row["status"], "status": "rolled-back", "recovered_by": run_key})
            attempt.update({"completed_at": utc_now(), "evidence_type": "live-native-delivery"})
            view.save(state)
            return attempt
        except Exception as exc:
            status = "reconcile-required"
            if not mutation_started:
                status = "failed-before-mutation"
            elif action == "promote":
                try:
                    view.check()
                    native = state.get("native", {}).get(environment, {})
                    retained = native.get("retained", {}).get(bundle["agent"])
                    if not retained or retained.get("release_digest") != digest:
                        expected = attempt.get("safe_before")
                        current_exists = foundry.get_agent(bundle["agent"]) is not None
                        owned = ledger.get("agents", {}).get(environment) == bundle["agent"]
                        unchanged = (not current_exists and expected is None and not owned)
                        if current_exists and expected is not None:
                            unchanged = runtime.snapshot(bundle["agent"]) == expected
                        elif current_exists and expected is None and owned:
                            current = runtime.snapshot(bundle["agent"])
                            baseline = foundry.get_version(bundle["agent"], current["version"])
                            baseline_record = ledger.get("definitions", {}).get(environment, {}).get(
                                fingerprint(BASELINE))
                            unchanged = (
                                baseline_record is not None
                                and baseline_record.get("definition") == BASELINE
                                and baseline_record.get("knowledge") is None
                                and baseline["status"] == "active"
                                and not baseline.get("draft", False)
                                and baseline.get("metadata", {}).get("purpose") == "prompt-pipeline-baseline-v1"
                                and project_shape(baseline["definition"], BASELINE) == BASELINE
                            )
                            if unchanged:
                                attempt["safe_before"] = current
                        if unchanged:
                            status = "failed-before-cutover"
                            attempt["verified_serving_unchanged"] = True
                except Exception as verification_error:
                    attempt["state_verification_error_type"] = type(verification_error).__name__
            attempt.update({"status": status, "error_type": type(exc).__name__, "completed_at": utc_now()})
            if isinstance(exc, LabError):
                attempt["reason"] = str(exc)[:300]
            view.save(state)
            raise
        finally:
            foundry.arm, foundry.search = original_arm, original_search


def public_receipt(result: dict) -> dict:
    return {key: result[key] for key in (
        "status", "environment", "action", "release_digest", "restored_release_digest",
        "full_gate_passed", "measured_upper_bound_usd", "evidence_type", "run_key",
    ) if key in result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--source-revision", required=True)
    prepare.add_argument("--tool-image-sha256", required=True)
    prepare.add_argument("--negative", action="store_true")
    for name in ("authorize", "run"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--environment", choices=ENVIRONMENTS, required=True)
        cmd.add_argument("--action", choices=tuple(WORKFLOWS), required=True)
        cmd.add_argument("--bundle", type=Path, required=True)
        cmd.add_argument("--digest", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            require(args.output.resolve().is_relative_to((Path.cwd() / ".lab").resolve()),
                    "Preparation output must stay inside ignored .lab")
            verify_source_revision(args.source_revision)
            source_hash, _ = acquire_source(args.output / "sources")
            bundle = release("prompt", args.source_revision, source_hash, negative=args.negative,
                             tool_image_sha256=args.tool_image_sha256, native_pipeline=True)
            with (args.output / "release.json").open("xb") as stream:
                stream.write(canonical(bundle))
            digest = fingerprint(bundle)
            if os.environ.get("GITHUB_OUTPUT"):
                with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                    stream.write(f"digest={digest}\n")
            result = {"digest": digest, "evidence_type": "local-preparation", "live_validation": False}
        else:
            policy, config = authorize(os.environ, args.environment, args.action, args.digest)
            verify_source_revision(policy["source_revision"])
            bundle = load(args.bundle, args.digest)
            require(bundle["runtime"] == "prompt"
                    and bundle["evaluation"]["version"] == NATIVE_EVALUATION_VERSION,
                    "Only the current native Prompt evaluation contract is supported")
            if args.command == "authorize":
                result = {"status": "delivery-policy-verified", "infrastructure_verified": False}
            else:
                from azure.identity import AzureCliCredential

                def reauthorize():
                    require(authorize(os.environ, args.environment, args.action, args.digest) == (policy, config),
                            "Delivery authorization changed")

                cache = {}

                def source_loader(source_hash):
                    if source_hash not in cache:
                        _, cache[source_hash] = acquire_source(
                            Path(".lab") / "pipeline-sources" / source_hash, source_hash)
                    return cache[source_hash]

                binding = config["current"]
                with AzureCliCredential(tenant_id=binding["tenant_id"]) as credential:
                    verify_ci_identity(credential, binding)
                    foundry = Foundry(binding["target"], credential)
                    upstream = Foundry(config["upstream"], credential) if config["upstream"] else None
                    try:
                        def upstream_check(environment, receipt):
                            require(upstream is not None and upstream.target["environment"] == environment,
                                    "Missing preceding-environment read identity")
                            snapshot = NativeRuntime(upstream, reauthorize).snapshot(bundle["agent"])
                            actual = upstream.get_version(bundle["agent"], snapshot["version"])
                            require(actual.get("metadata", {}).get("release_digest") == receipt["release_digest"],
                                    "Upstream version metadata differs")
                            return snapshot

                        journal = BlobJournal(config["journal_endpoint"], credential)
                        run_key = "-".join((os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"],
                                            args.environment, args.action))
                        result = public_receipt(execute(
                            foundry, journal, policy, config, bundle, args.digest, run_key, args.action,
                            reauthorize, source_loader, upstream_check))
                    finally:
                        foundry.close()
                        if upstream:
                            upstream.close()
        sys.stdout.write(canonical(result).decode())
        return 1 if result.get("status") == "rejected" else 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, LabError) else "Private operation failed; inspect the protected journal"
        sys.stderr.write(canonical({"status": "error", "reason": message, "error_type": type(exc).__name__}).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
