"""Persistent simulated release controller, never a production serving router."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from . import artifacts, bindings
from .contracts import (
    ENVIRONMENTS, LabError, canonical, digest_value, fields, fingerprint, identifier, parse_json,
    require, text, utc_now,
)
from .evaluation import evaluate
from .locks import resource_locks


class ReleaseLab:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        database = root / "releases.sqlite3"
        with resource_locks(root / "locks", ["initialize"]):
            existing = database.exists()
            with self._connect() as db:
                if existing:
                    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    require("lab_meta" in names, "Refusing an unrelated or incomplete database")
                    require(db.execute("SELECT version, evidence_type FROM lab_meta").fetchall() ==
                            [(1, "simulated")], "Unsupported local database format")
                else:
                    db.executescript("""
                        CREATE TABLE lab_meta(version INTEGER, evidence_type TEXT);
                        INSERT INTO lab_meta VALUES (1, 'simulated');
                        CREATE TABLE candidates(
                            id TEXT PRIMARY KEY, agent TEXT, environment TEXT, payload TEXT,
                            evaluation TEXT, approval TEXT, retained INTEGER NOT NULL DEFAULT 0);
                        CREATE TABLE serving(
                            agent TEXT, environment TEXT, candidate_id TEXT, generation INTEGER,
                            PRIMARY KEY(agent, environment));
                        CREATE TABLE attempts(
                            id TEXT PRIMARY KEY, operation TEXT, agent TEXT, environment TEXT,
                            started_at TEXT, ended_at TEXT, outcome TEXT, details TEXT);
                        CREATE TABLE retired(
                            environment TEXT, name TEXT, digest TEXT,
                            PRIMARY KEY(environment, name, digest));
                    """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.root / "releases.sqlite3", timeout=5)) as db:
            with db:
                yield db

    @staticmethod
    def _snapshot(db: sqlite3.Connection, agent: str, environment: str) -> dict[str, Any]:
        row = db.execute("SELECT candidate_id, generation FROM serving WHERE agent=? AND environment=?",
                         (agent, environment)).fetchone()
        return {"candidate_id": row[0], "generation": row[1]} if row else {
            "candidate_id": None, "generation": 0,
        }

    def serving(self, agent: str, environment: str) -> dict[str, Any]:
        with self._connect() as db:
            return self._snapshot(db, agent, environment)

    @staticmethod
    def _candidate(db: sqlite3.Connection, candidate_id: str) -> dict[str, Any]:
        row = db.execute("SELECT payload, evaluation, approval, retained FROM candidates WHERE id=?",
                         (candidate_id,)).fetchone()
        require(row is not None, "Unknown candidate")
        return {**parse_json(row[0]), "evaluation": parse_json(row[1]) if row[1] else None,
                "approval": parse_json(row[2]) if row[2] else None, "retained": bool(row[3])}

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        with self._connect() as db:
            return self._candidate(db, candidate_id)

    def _run(self, operation: str, agent: str, environment: str, components: list[str],
             action: Callable[[sqlite3.Connection], dict[str, Any]]) -> dict[str, Any]:
        identifier(agent, "agent")
        require(environment in ENVIRONMENTS, "Unknown environment")
        keys = [f"{environment}/agent/{agent}", *[f"{environment}/component/{name}" for name in components]]
        attempt_id = str(uuid.uuid4())
        result: dict[str, Any]
        with self._connect() as db:
            db.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?, NULL, 'started', '{}')",
                       (attempt_id, operation, agent, environment, utc_now()))
            db.commit()
            with ExitStack() as locks:
                try:
                    locks.enter_context(resource_locks(self.root / "locks", keys))
                    db.execute("BEGIN IMMEDIATE")
                    result = action(db)
                    outcome = "rejected" if "error" in result else "succeeded"
                    db.execute("UPDATE attempts SET ended_at=?, outcome=?, details=? WHERE id=?",
                               (utc_now(), outcome, canonical(result).decode(), attempt_id))
                    db.commit()
                except (LabError, sqlite3.Error, OSError) as exc:
                    db.rollback()
                    db.execute("UPDATE attempts SET ended_at=?, outcome='rejected', details=? WHERE id=?",
                               (utc_now(), canonical({"error": str(exc)}).decode(), attempt_id))
                    db.commit()
                    raise
        if "error" in result:
            raise LabError(result["error"])
        return {"attempt_id": attempt_id, "evidence_type": "simulated", **result}

    def create(self, bundle_path: Path, digest: str, binding: dict, content: dict, state: dict,
               readiness: dict) -> dict[str, Any]:
        bundle = artifacts.load(bundle_path, digest)
        manifest = bundle["manifest"]
        require(isinstance(binding, dict) and "environment" in binding, "Environment binding required")
        refs = artifacts.references(bundle)

        def action(db):
            context = bindings.validate(bundle, binding, content, state)
            fields(readiness, {"evidence_type", "identity", "access", "status"})
            require(readiness["evidence_type"] == "simulated", "Live readiness is not implemented")
            text(readiness["identity"], "synthetic identity")
            require(readiness["access"] is True and readiness["status"] == "completed",
                    "Candidate readiness/access did not pass")
            for name, reference in refs["components"].items():
                require(db.execute("SELECT 1 FROM retired WHERE environment=? AND name=? AND digest=?",
                                   (binding["environment"], name, reference["digest"])).fetchone() is None,
                        "Candidate references a retired component")
            before = self._snapshot(db, manifest["agent"], binding["environment"])
            candidate_id = str(uuid.uuid4())
            payload = {
                "id": candidate_id, "created_at": utc_now(), "policy": refs["policy"],
                "binding": binding, "content": content, "state": state, "readiness": readiness,
                "component_contracts": refs["components"],
                "context": {
                    "candidate_id": candidate_id, "release_digest": digest,
                    "agent": manifest["agent"], "runtime": manifest["runtime"],
                    "environment": binding["environment"], "readiness_digest": fingerprint(readiness),
                    **context,
                },
            }
            db.execute("INSERT INTO candidates(id, agent, environment, payload) VALUES (?, ?, ?, ?)",
                       (candidate_id, manifest["agent"], binding["environment"], canonical(payload).decode()))
            after = self._snapshot(db, manifest["agent"], binding["environment"])
            require(after == before, "Candidate changed serving")
            return {"candidate_id": candidate_id, "serving_before": before,
                    "serving_during": before, "serving_after": after}

        return self._run("create", manifest["agent"], binding["environment"], list(refs["components"]), action)

    def _for_candidate(self, operation: str, candidate_id: str, action: Callable) -> dict[str, Any]:
        candidate = self.candidate(candidate_id)
        context = candidate["context"]
        return self._run(operation, context["agent"], context["environment"],
                         list(context["component_digests"]),
                         lambda db: action(db, self._candidate(db, candidate_id)))

    def record_evaluation(self, candidate_id: str, report: dict) -> dict[str, Any]:
        def action(db, candidate):
            db.execute("UPDATE candidates SET evaluation=NULL, approval=NULL WHERE id=?", (candidate_id,))
            try:
                evaluate(candidate, report)
            except LabError as exc:
                return {"error": str(exc)}
            db.execute("UPDATE candidates SET evaluation=? WHERE id=?", (canonical(report).decode(), candidate_id))
            return {"candidate_id": candidate_id, "evaluation_digest": fingerprint(report)}
        return self._for_candidate("evaluate", candidate_id, action)

    def approve(self, candidate_id: str, approver: str) -> dict[str, Any]:
        def action(db, candidate):
            text(approver, "synthetic approver")
            require(candidate["evaluation"] is not None, "No passing evaluation")
            evaluate(candidate, candidate["evaluation"])
            context = candidate["context"]
            approval = {
                "evidence_type": "simulated", "approver": approver, "approved_at": utc_now(),
                "context_digest": fingerprint(context),
                "evaluation_digest": fingerprint(candidate["evaluation"]),
                "expected_serving": self._snapshot(db, context["agent"], context["environment"]),
            }
            db.execute("UPDATE candidates SET approval=? WHERE id=?", (canonical(approval).decode(), candidate_id))
            return {"candidate_id": candidate_id, "approval": approval}
        return self._for_candidate("approve", candidate_id, action)

    def promote(self, candidate_id: str, expected_serving: dict, *, rollback: bool = False) -> dict[str, Any]:
        def action(db, candidate):
            context = candidate["context"]
            before = self._snapshot(db, context["agent"], context["environment"])
            fields(expected_serving, {"candidate_id", "generation"})
            require(type(expected_serving["generation"]) is int, "Integer serving generation required")
            require(before == expected_serving, "Serving changed since caller observation")
            require(candidate["evaluation"] is not None, "No passing evaluation")
            evaluate(candidate, candidate["evaluation"])
            approval = candidate["approval"]
            require(approval is not None and
                    approval["context_digest"] == fingerprint(context) and
                    approval["evaluation_digest"] == fingerprint(candidate["evaluation"]) and
                    approval["expected_serving"] == before, "Missing or stale candidate approval")
            require(before["candidate_id"] != candidate_id, "Candidate already serves")
            for name, digest in context["component_digests"].items():
                require(db.execute("SELECT 1 FROM retired WHERE environment=? AND name=? AND digest=?",
                                   (context["environment"], name, digest)).fetchone() is None,
                        "Promotion references a retired component")
            if rollback:
                require(candidate["retained"], "Rollback target was not previously approved for serving")
            elif context["environment"] != "dev":
                previous_env = ENVIRONMENTS[ENVIRONMENTS.index(context["environment"]) - 1]
                previous = self._snapshot(db, context["agent"], previous_env)
                require(previous["candidate_id"] is not None, "Previous environment has no approved release")
                previous_candidate = self._candidate(db, previous["candidate_id"])
                require(previous_candidate["context"]["release_digest"] == context["release_digest"],
                        "Previous environment serves a different release digest")
            if before["candidate_id"]:
                previous_candidate = self._candidate(db, before["candidate_id"])
                require(previous_candidate["context"]["runtime"] == context["runtime"],
                        "Runtime change requires a separately named agent")
                for name, reference in candidate["component_contracts"].items():
                    if reference["kind"] == "memory-policy":
                        previous_binding = previous_candidate["binding"]["components"].get(name)
                        require(previous_binding == candidate["binding"]["components"][name],
                                "Memory store/policy change requires verified migration; unsupported by controller")
            db.execute("INSERT INTO serving VALUES (?, ?, ?, ?) ON CONFLICT(agent, environment) "
                       "DO UPDATE SET candidate_id=excluded.candidate_id, generation=excluded.generation",
                       (context["agent"], context["environment"], candidate_id, before["generation"] + 1))
            db.execute("UPDATE candidates SET retained=1, approval=NULL WHERE id=?", (candidate_id,))
            after = self._snapshot(db, context["agent"], context["environment"])
            require(after == {"candidate_id": candidate_id, "generation": before["generation"] + 1},
                    "Simulated serving read-back mismatch")
            return {"candidate_id": candidate_id, "serving_before": before, "serving_after": after,
                    "verification": "local-database-only"}
        return self._for_candidate("rollback" if rollback else "promote", candidate_id, action)

    def retire_component(self, environment: str, name: str, digest: str) -> dict[str, Any]:
        identifier(name, "component name")
        digest_value(digest, "component digest")

        def action(db):
            for (payload,) in db.execute("SELECT payload FROM candidates WHERE environment=? AND retained=1",
                                        (environment,)):
                candidate = parse_json(payload)
                require(candidate["context"]["component_digests"].get(name) != digest,
                        "Component retained by a serving or rollback-eligible consumer")
            db.execute("INSERT OR IGNORE INTO retired VALUES (?, ?, ?)", (environment, name, digest))
            return {"component": name, "digest": digest, "environment": environment}
        return self._run("retire-component", "component-owner", environment, [name], action)

    def history(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [
                {"attempt_id": row[0], "operation": row[1], "agent": row[2], "environment": row[3],
                 "started_at": row[4], "ended_at": row[5], "outcome": row[6],
                 "evidence_type": "simulated", "details": parse_json(row[7])}
                for row in db.execute("SELECT * FROM attempts ORDER BY rowid")
            ]
