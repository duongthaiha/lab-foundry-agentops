"""Replay controller invariants with fabricated results, not live agent calls."""

from pathlib import Path

from . import artifacts, bindings
from .contracts import ENVIRONMENTS, RUNTIMES, LabError, canonical, require, utc_now
from .examples import write_example
from .releases import ReleaseLab
from .simulation_state import SyntheticJournal, SyntheticScope


PLACEHOLDER_APPROVER = "placeholder-only-not-a-live-approval"


def fixture_report(candidate: dict, *, passes: bool = True) -> dict:
    return {
        "evidence_type": "simulated", "status": "completed", "context": candidate["context"],
        "completed_at": utc_now(), "metrics": {
            "quality": 1 if passes else 0, "unsafe": 0, "latency_ms": 100, "cost_usd": 0.001,
        },
    }


def memory_demo(root: Path, runtime: str, environment: str) -> dict:
    scope = SyntheticScope(environment, f"contoso-{runtime}", "synthetic-user", "evaluation")
    journal = SyntheticJournal(root, scope)
    for store in ("old", "new"):
        journal.create_store(store)
    journal.append(scope, "remember", value="concise")
    for store in ("old", "new"):
        journal.replay(store)
    before = journal.read("old", scope, 0)
    journal.append(scope, "after-cutover", value="detailed")
    journal.replay("new")
    try:
        journal.replay("old", fail_at_sequence=2)
    except LabError as exc:
        require("Injected" in str(exc), "Unexpected memory-demo failure")
    else:
        raise LabError("Expected partial-write failure was not observed")
    during = {"old": journal.read("old", scope, 0), "new": journal.read("new", scope, 0)}
    try:
        journal.require_reconciled(("old", "new"), 0)
    except LabError as exc:
        require("lag" in str(exc), "Unexpected reconciliation failure")
    else:
        raise LabError("Unsafe rollback was not blocked")
    recovered = SyntheticJournal(root, scope)
    recovered.replay("old")
    repaired = recovered.require_reconciled(("old", "new"), 0)
    recovered.append(scope, "forget-after-cutover", value=None, delete=True)
    for store in ("new", "old"):
        recovered.replay(store)
    forgotten = recovered.read("old", scope, 0)
    recovered.append(scope, "expires", value="concise", expires_at=10)
    for store in ("new", "old"):
        recovered.replay(store)
    proof = recovered.require_reconciled(("old", "new"), 10)
    after = recovered.read("old", scope, 10)
    require(forgotten == {} and after == {}, "Synthetic deletion or expiry resurrected state")
    return {
        "evidence_type": "simulated", "runtime": runtime, "environment": environment,
        "before": before, "during": during, "repaired": repaired,
        "forgotten": forgotten, "after_expiry": after, "reconciliation": proof,
        "unsafe_rollback_blocked": True,
    }


def demo(root: Path, revision: str) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    lab = ReleaseLab(root / "state")
    reports = root / "evaluations"
    reports.mkdir()
    records = root / "records"
    records.mkdir()
    result = {
        "evidence_type": "simulated",
        "warning": "No Azure calls, measured model metrics, actual runtime authorization, or deployment proof.",
        "approval_mode": "placeholder",
        "live_authorization": False,
        "failed_evaluation_approval_blocks": 0,
        "runtimes": {}, "memory": [],
        "harness_memory": "unsupported-no-substitute",
    }

    def evaluate_and_approve(candidate_id):
        report = fixture_report(lab.candidate(candidate_id))
        output = reports / f"{candidate_id}-{len(lab.history())}-pass.json"
        output.write_bytes(canonical(report))
        lab.record_evaluation(candidate_id, report)
        lab.approve(candidate_id, PLACEHOLDER_APPROVER)

    for runtime in RUNTIMES:
        runtime_records = {"releases": {}, "rollback": {}}
        ids = {}
        for version in ("1", "2"):
            source = root / "sources" / runtime / version
            write_example(source, runtime, revision, version)
            path, digest = artifacts.build(source, root / "bundles")
            bundle = artifacts.load(path, digest)
            runtime_records["releases"][version] = {"digest": digest, "environments": {}}
            for environment in ENVIRONMENTS:
                binding, content, state = bindings.synthetic_records(bundle, environment)
                for category, value in (("binding", binding), ("content", content), ("state", state)):
                    (records / f"{runtime}-{version}-{environment}-{category}.json").write_bytes(canonical(value))
                created = lab.create(path, digest, binding, content, state, {
                    "evidence_type": "simulated", "identity": f"synthetic-{environment}-{runtime}",
                    "access": True, "status": "completed",
                })
                candidate_id = created["candidate_id"]
                ids[version, environment] = candidate_id
                if version == "2":
                    failing = fixture_report(lab.candidate(candidate_id), passes=False)
                    (reports / f"{candidate_id}-fail.json").write_bytes(canonical(failing))
                    before = lab.serving("contoso-" + runtime, environment)
                    try:
                        lab.record_evaluation(candidate_id, failing)
                    except LabError as exc:
                        require("threshold failed" in str(exc), "Unexpected rejection in demo")
                    else:
                        raise LabError("Failing candidate was not rejected")
                    require(before == lab.serving("contoso-" + runtime, environment),
                            "Rejected candidate changed serving")
                    try:
                        lab.approve(candidate_id, PLACEHOLDER_APPROVER)
                    except LabError as exc:
                        require("No passing evaluation" in str(exc), "Unexpected placeholder-approval failure")
                    else:
                        raise LabError("Placeholder approval bypassed a failed evaluation")
                    result["failed_evaluation_approval_blocks"] += 1
                evaluate_and_approve(candidate_id)
                promoted = lab.promote(candidate_id, lab.serving("contoso-" + runtime, environment))
                runtime_records["releases"][version]["environments"][environment] = {
                    "candidate": lab.candidate(candidate_id), "creation": created, "promotion": promoted,
                }
        for environment in reversed(ENVIRONMENTS):
            previous = ids["1", environment]
            evaluate_and_approve(previous)
            runtime_records["rollback"][environment] = lab.promote(
                previous, lab.serving("contoso-" + runtime, environment), rollback=True)
        tool_digest = lab.candidate(ids["1", "dev"])["context"]["component_digests"]["contoso-tool"]
        try:
            lab.retire_component("dev", "contoso-tool", tool_digest)
        except LabError as exc:
            require("retained" in str(exc), "Unexpected component-retirement failure")
        else:
            raise LabError("Rollback dependency retirement was not blocked")
        runtime_records["retirement_blocked"] = True
        result["runtimes"][runtime] = runtime_records
        if runtime != "harness":
            for environment in ENVIRONMENTS:
                result["memory"].append(memory_demo(root / "memory" / runtime / environment, runtime, environment))
    result["attempts"] = lab.history()
    (root / "report.json").write_bytes(canonical(result))
    return {
        "evidence_type": "simulated", "report": str(root / "report.json"),
        "approval_mode": result["approval_mode"], "live_authorization": False,
        "runtimes": len(result["runtimes"]), "environments": list(ENVIRONMENTS),
        "attempts": len(result["attempts"]),
        "rejected_attempts": sum(attempt["outcome"] == "rejected" for attempt in result["attempts"]),
        "placeholder_approvals": sum(attempt["operation"] == "approve" and attempt["outcome"] == "succeeded"
                                     for attempt in result["attempts"]),
        "failed_evaluation_approval_blocks": result["failed_evaluation_approval_blocks"],
        "live_validation": False,
    }
