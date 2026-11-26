"""Synthetic reconciliation model. Not a Foundry Memory implementation."""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .contracts import (
    ENVIRONMENTS, LabError, canonical, finite, fingerprint, identifier, parse_json, require, text,
)
from .locks import resource_locks


@dataclass(frozen=True)
class SyntheticScope:
    environment: str
    agent: str
    user: str
    purpose: str

    def validate(self):
        require(self.environment in ENVIRONMENTS, "Unknown synthetic scope environment")
        for value in (self.agent, self.user):
            identifier(value, "synthetic scope")
        require(self.purpose in ("evaluation", "serving"), "Unknown synthetic scope purpose")


class SyntheticJournal:
    def __init__(self, root: Path, scope: SyntheticScope):
        scope.validate()
        self.root, self.scope = root, scope
        root.mkdir(parents=True, exist_ok=True)
        with resource_locks(root / "locks", ["journal-initialize"]):
            existing = (root / "synthetic-memory.sqlite3").exists()
            with self._connect() as db:
                if existing:
                    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    require("scope" in names, "Refusing an unrelated or incomplete state database")
                    require(db.execute("SELECT data FROM scope").fetchall() ==
                            [(canonical(asdict(scope)).decode(),)], "Cross-scope journal access denied")
                else:
                    db.executescript("""
                        CREATE TABLE scope(data TEXT NOT NULL);
                        CREATE TABLE operations(
                            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                            operation_id TEXT NOT NULL UNIQUE, data TEXT NOT NULL);
                        CREATE TABLE checkpoints(store TEXT PRIMARY KEY, sequence INTEGER NOT NULL);
                        CREATE TABLE records(
                            store TEXT, key TEXT, sequence INTEGER, data TEXT,
                            PRIMARY KEY(store, key));
                    """)
                    db.execute("INSERT INTO scope VALUES (?)", (canonical(asdict(scope)).decode(),))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.root / "synthetic-memory.sqlite3", timeout=5)) as db:
            with db:
                yield db

    def _authorize(self, caller: SyntheticScope):
        require(caller == self.scope, "Cross-scope synthetic operation denied")

    def create_store(self, name: str):
        identifier(name, "store")
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO checkpoints VALUES (?, 0)", (name,))

    def append(self, caller: SyntheticScope, operation_id: str, *, value: str | None,
               expires_at: float | None = None, delete: bool = False) -> int:
        self._authorize(caller)
        text(operation_id, "operation ID")
        require(type(delete) is bool, "Deletion flag must be boolean")
        if delete:
            require(value is None and expires_at is None, "Deletion cannot carry a value or TTL")
        else:
            require(value in ("concise", "detailed"), "Synthetic fixture rejected by preference allowlist")
            if expires_at is not None:
                require(finite(expires_at, "expiry") >= 0, "Negative expiry")
        data = canonical({"key": "preferred-answer-format", "value": value,
                          "expires_at": expires_at, "deleted": delete}).decode()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT sequence, data FROM operations WHERE operation_id=?",
                                  (operation_id,)).fetchone()
            if existing:
                require(existing[1] == data, "Operation ID reused with different intent")
                return existing[0]
            cursor = db.execute("INSERT INTO operations(operation_id, data) VALUES (?, ?)", (operation_id, data))
            return cursor.lastrowid

    def replay(self, store: str, *, fail_at_sequence: int | None = None) -> int:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            checkpoint = db.execute("SELECT sequence FROM checkpoints WHERE store=?", (store,)).fetchone()
            require(checkpoint is not None, "Unknown synthetic store")
            operations = db.execute("SELECT sequence, data FROM operations WHERE sequence>? ORDER BY sequence",
                                    (checkpoint[0],)).fetchall()
            db.commit()
            for sequence, data in operations:
                db.execute("BEGIN IMMEDIATE")
                record = parse_json(data)
                db.execute("INSERT INTO records VALUES (?, ?, ?, ?) ON CONFLICT(store, key) DO UPDATE SET "
                           "sequence=excluded.sequence, data=excluded.data WHERE records.sequence<excluded.sequence",
                           (store, record["key"], sequence, data))
                if sequence == fail_at_sequence:
                    raise LabError("Injected synthetic write failure before checkpoint")
                db.execute("UPDATE checkpoints SET sequence=MAX(sequence, ?) WHERE store=?", (sequence, store))
                db.commit()
            return db.execute("SELECT sequence FROM checkpoints WHERE store=?", (store,)).fetchone()[0]

    @staticmethod
    def _snapshot(db: sqlite3.Connection, store: str, now: float) -> dict:
        result = {}
        for key, data in db.execute("SELECT key, data FROM records WHERE store=?", (store,)):
            record = parse_json(data)
            if not record["deleted"] and (record["expires_at"] is None or record["expires_at"] > now):
                result[key] = record["value"]
        return result

    def read(self, store: str, caller: SyntheticScope, now: float) -> dict:
        self._authorize(caller)
        finite(now, "read time")
        with self._connect() as db:
            require(db.execute("SELECT 1 FROM checkpoints WHERE store=?", (store,)).fetchone() is not None,
                    "Unknown synthetic store")
            return self._snapshot(db, store, now)

    def require_reconciled(self, stores: tuple[str, ...], now: float) -> dict:
        require(len(stores) >= 2 and len(set(stores)) == len(stores), "Two distinct stores required")
        finite(now, "reconciliation time")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            high_water = db.execute("SELECT COALESCE(MAX(sequence), 0) FROM operations").fetchone()[0]
            expected = {}
            for (data,) in db.execute("SELECT data FROM operations ORDER BY sequence"):
                record = parse_json(data)
                expected[record["key"]] = data
            for store in stores:
                checkpoint = db.execute("SELECT sequence FROM checkpoints WHERE store=?", (store,)).fetchone()
                require(checkpoint is not None and checkpoint[0] == high_water,
                        "Unsafe migration or rollback: journal lag")
                actual = dict(db.execute("SELECT key, data FROM records WHERE store=?", (store,)))
                require(actual == expected, "Unsafe migration or rollback: state mismatch")
            return {
                "evidence_type": "simulated", "scope_digest": fingerprint(asdict(self.scope)),
                "checkpoint": high_water, "stores": list(stores),
                "state_digest": fingerprint(self._snapshot(db, stores[0], now)),
            }
