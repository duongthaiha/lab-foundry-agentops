"""Run with python -m agentops. Mutations require explicit simulated mode."""

import argparse
import sqlite3
import sys
from pathlib import Path

from . import artifacts
from .contracts import ENVIRONMENTS, RUNTIMES, LabError, canonical, read_json, require
from .examples import write_example
from .releases import ReleaseLab
from .simulation import demo


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Local AgentOps controls; no Azure adapter exists.")
    result.add_argument("--mode", choices=("simulated", "live"), required=True)
    result.add_argument("--state", type=Path, default=Path(".lab") / "state")
    commands = result.add_subparsers(dest="command", required=True)
    example = commands.add_parser("example", help="Generate synthetic inputs, not Foundry deployment schemas")
    example.add_argument("--source", type=Path, required=True)
    example.add_argument("--runtime", choices=RUNTIMES, required=True)
    example.add_argument("--source-revision", required=True)
    example.add_argument("--version", default="1")
    build = commands.add_parser("build")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--digest", required=True)
    create = commands.add_parser("candidate")
    create.add_argument("--bundle", type=Path, required=True)
    create.add_argument("--digest", required=True)
    for key in ("binding", "content", "state-evidence", "readiness"):
        create.add_argument("--" + key, type=Path, required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--candidate", required=True)
    evaluation.add_argument("--report", type=Path, required=True)
    approve = commands.add_parser("approve", help="Record a simulated approval, not authenticated authority")
    approve.add_argument("--candidate", required=True)
    approve.add_argument("--approver", required=True)
    for operation in ("promote", "rollback"):
        promote = commands.add_parser(operation)
        promote.add_argument("--candidate", required=True)
        promote.add_argument("--expected-candidate", required=True, help="Exact current ID, or none")
        promote.add_argument("--expected-generation", type=int, required=True)
    serving = commands.add_parser("serving")
    serving.add_argument("--agent", required=True)
    serving.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    info = commands.add_parser("candidate-info")
    info.add_argument("--candidate", required=True)
    retire = commands.add_parser("retire-component")
    retire.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    retire.add_argument("--name", required=True)
    retire.add_argument("--digest", required=True)
    commands.add_parser("history")
    replay = commands.add_parser("demo", help="Fabricated three-runtime release and state-recovery demo")
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--source-revision", required=True)
    return result


def run(args):
    require(args.mode == "simulated",
            "Live operations are unavailable: Foundry prerequisite, adapters, target and cost gates are unresolved")
    if args.command == "example":
        write_example(args.source, args.runtime, args.source_revision, args.version)
        return {"source": str(args.source), "runtime": args.runtime}
    if args.command == "build":
        path, digest = artifacts.build(args.source, args.output)
        return {"bundle": str(path), "digest": digest}
    if args.command == "verify":
        artifacts.load(args.bundle, args.digest)
        return {"verified_digest": args.digest}
    if args.command == "demo":
        return demo(args.output, args.source_revision)
    lab = ReleaseLab(args.state)
    if args.command == "candidate":
        return lab.create(args.bundle, args.digest, read_json(args.binding), read_json(args.content),
                          read_json(args.state_evidence), read_json(args.readiness))
    if args.command == "evaluate":
        return lab.record_evaluation(args.candidate, read_json(args.report))
    if args.command == "approve":
        return lab.approve(args.candidate, args.approver)
    if args.command in ("promote", "rollback"):
        return lab.promote(args.candidate, {
            "candidate_id": None if args.expected_candidate == "none" else args.expected_candidate,
            "generation": args.expected_generation,
        }, rollback=args.command == "rollback")
    if args.command == "serving":
        return lab.serving(args.agent, args.environment)
    if args.command == "candidate-info":
        return lab.candidate(args.candidate)
    if args.command == "retire-component":
        return lab.retire_component(args.environment, args.name, args.digest)
    return lab.history()


def main() -> int:
    args = parser().parse_args()
    try:
        result = run(args)
        sys.stdout.write(canonical({"evidence_type": "simulated", "result": result}).decode())
        return 0
    except (LabError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(canonical({"status": "error", "error": str(exc)}).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
