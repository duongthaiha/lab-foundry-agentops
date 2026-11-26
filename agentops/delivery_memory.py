"""Native scoped-memory primitives with explicit retention/migration limitations."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Callable
from uuid import UUID

from azure.ai.projects.models import (
    MemorySearchOptions, MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions,
)
from azure.core.exceptions import ResourceNotFoundError
from azure.core.rest import HttpRequest

from .contracts import ENVIRONMENTS, fingerprint, identifier, require, utc_now
from .delivery_azure import project_shape

HEADERS = {"Foundry-Features": "MemoryStores=V1Preview"}


class NativeMemory:
    """Caller identity must come from verified authentication, never prompt text."""

    def __init__(self, project, runtime: str, store: str, caller_oid: str, allowed_callers: set[str],
                 check_write: Callable[[], None]):
        require(runtime in ("prompt", "hosted"), "Harness memory is unsupported; no substitute")
        require(str(UUID(caller_oid)) == caller_oid and caller_oid in allowed_callers,
                "Authenticated caller is outside the synthetic memory allowlist")
        require(store.startswith("contoso-memory-"), "Only lab-owned synthetic memory stores are allowed")
        identifier(store, "memory store")
        self.runtime = runtime
        self.check_write = check_write
        self.project, self.api, self.store, self.scope = project, project.beta.memory_stores, store, caller_oid

    @staticmethod
    def definition() -> dict:
        return MemoryStoreDefaultDefinition(
            chat_model="gpt-5-mini", embedding_model="text-embedding-3-small",
            options=MemoryStoreDefaultOptions(
                user_profile_enabled=True, chat_summary_enabled=False, procedural_memory_enabled=False,
                user_profile_details="Only fictional Contoso lab preferences; never personal information.",
                default_ttl_seconds=timedelta(days=1),
            ),
        ).as_dict()

    def ensure_store(self) -> dict:
        desired = self.definition()
        try:
            result = self.api.get(self.store, headers=HEADERS).as_dict()
        except ResourceNotFoundError:
            self.check_write()
            self.api.create(name=self.store, definition=MemoryStoreDefaultDefinition(desired), headers=HEADERS)
            result = self.api.get(self.store, headers=HEADERS).as_dict()
        require(project_shape(result["definition"], desired) == desired, "Native memory policy drift")
        return {"store": self.store, "policy_digest": fingerprint(desired)}

    def snapshot(self) -> dict:
        items = []
        for item in self.api.list_memories(self.store, scope=self.scope, limit=100, headers=HEADERS):
            value = item.as_dict()
            require(value["scope"] == self.scope, "Native memory enumeration crossed caller scope")
            items.append(value)
            require(len(items) <= 100, "Synthetic memory scope exceeds the lab limit")
        items.sort(key=lambda item: item["memory_id"])
        return {"store": self.store, "scope_digest": fingerprint(self.scope),
                "watermark": fingerprint(items), "count": len(items), "observed_at": utc_now(),
                "records": items}

    def learn_fixture(self, remember_operation: Callable[[dict], None]) -> dict:
        """Only this fixed fictional preference can be written by the lab helper."""
        before = self.snapshot()
        remember_operation({"status": "starting", "store": self.store,
                            "scope_digest": fingerprint(self.scope), "before_watermark": before["watermark"]})
        self.check_write()
        poller = self.api.begin_update_memories(
            self.store, scope=self.scope, update_delay=0,
            items=[{"role": "user", "type": "message",
                    "content": "In this fictional Contoso lab, I prefer numbered troubleshooting steps."}],
            # Preserve the service's status and usage; the SDK's default deserializer
            # synthesizes zero usage if the response has no completed result.
            cls=lambda response, parsed, headers: response.http_response.json(),
            headers=HEADERS,
        )
        update_id = poller.update_id
        require(isinstance(update_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", update_id) is not None,
                "Native memory update ID missing")
        remember_operation({"status": "pending", "update_id": update_id})
        value = poller.result(timeout=300)
        require(poller.done(), "Native memory update exceeded five minutes; remote operation may continue, reconcile before retrying")
        require(value["update_id"] == update_id, "Native memory completion belongs to another operation")
        return self.finish_update(value, before["watermark"])

    def read_update(self, update_id: str) -> dict:
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", update_id) is not None, "Invalid native update ID")
        # This is the same status route used by the SDK's native memory poller.
        # {endpoint} is resolved by the project's authenticated send_request method.
        response = self.project.send_request(HttpRequest(
            "GET", f"{{endpoint}}/memory_stores/{self.store}/updates/{update_id}?api-version=v1",
            headers=HEADERS,
        ), redirect_max=0)
        try:
            require(response.status_code == 200, f"Native memory status read failed: HTTP {response.status_code}")
            value = response.json()
            require(value["update_id"] == update_id and value["status"] in (
                "queued", "in_progress", "completed", "failed", "superseded"), "Native update read-back mismatch")
            return value
        finally:
            response.close()

    def finish_update(self, value: dict, before_watermark: str) -> dict:
        require(value["status"] == "completed" and value.get("result"), "Native memory update did not complete")
        require(all(operation["memory_item"]["scope"] == self.scope
                    for operation in value["result"]["memory_operations"]), "Memory update crossed caller scope")
        usage = value["result"].get("usage")
        require(isinstance(usage, dict) and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("embedding_tokens", "input_tokens", "output_tokens", "total_tokens")),
            "Native memory usage was not returned")
        after = self.snapshot()
        require(after["count"] > 0, "No native memory was extracted")
        return {"before_watermark": before_watermark, "after_watermark": after["watermark"],
                "update_id": value["update_id"], "operation_digest": fingerprint(value["result"]["memory_operations"]),
                "usage": value["result"]["usage"], "scope_digest": after["scope_digest"]}

    def recall(self) -> dict:
        value = self.api.search_memories(
            self.store, scope=self.scope, items="What troubleshooting format does this synthetic lab caller prefer?",
            options=MemorySearchOptions(max_memories=5), headers=HEADERS,
        ).as_dict()
        require(value.get("usage") is not None, "Native recall usage missing")
        for item in value["memories"]:
            require(item["memory_item"]["scope"] == self.scope, "Native recall crossed caller scope")
        return {"count": len(value["memories"]), "result_digest": fingerprint(value["memories"]),
                "search_id": value["search_id"], "usage": value["usage"],
                "scope_digest": fingerprint(self.scope)}

    def forget(self) -> dict:
        before = self.snapshot()
        self.check_write()
        value = self.api.delete_scope(self.store, scope=self.scope, headers=HEADERS).as_dict()
        require(value["deleted"] is True and value["scope"] == self.scope and value["name"] == self.store,
                "Native scope deletion was not confirmed")
        after = self.snapshot()
        require(after["count"] == 0, "Native scope still contains memories after deletion")
        return {"before_watermark": before["watermark"], "after_watermark": after["watermark"],
                "scope_digest": after["scope_digest"], "deleted": True}

    def migration_plan(self, target: "NativeMemory") -> dict:
        require(target.scope == self.scope and target.store != self.store, "Migration scope or target mismatch")
        source, destination = self.snapshot(), target.snapshot()
        require(destination["count"] == 0, "Migration target is not empty")
        # Native create_memory cannot preserve updated_at/expiry. A copy would restart
        # the one-day TTL and could resurrect or extend retained records.
        return {"source_store": self.store, "target_store": target.store,
                "source_watermark": source["watermark"], "target_watermark": destination["watermark"],
                "scope_digest": source["scope_digest"], "copy_allowed": False,
                "empty_scope_cutover_allowed": source["count"] == 0,
                "blocking": [] if source["count"] == 0 else [
                    "Native create_memory exposes no original timestamp/expiry parameter; lossless TTL-preserving migration is unverified"
                ]}

    def prompt_tool(self) -> dict:
        require(self.runtime == "prompt", "Hosted memory uses direct native APIs, not a Prompt tool")
        return {"type": "memory_search_preview", "memory_store_name": self.store,
                "scope": "{{$userId}}", "search_options": {"max_memories": 5}, "update_delay": 0}


class MemoryDelivery:
    """Coordinate participating writers; this does not quiesce automatic runtime writes."""

    def __init__(self, memory: NativeMemory, journal, environment: str):
        require(environment in ENVIRONMENTS, "Unknown memory environment")
        self.memory, self.journal = memory, journal
        self.memory.check_write = journal.check
        self.key = fingerprint({"environment": environment, "store": memory.store, "scope": memory.scope})

    def learn(self) -> dict:
        with self.journal.locked() as state:
            records = state.setdefault("memory_updates", {})
            prior = records.get(self.key)
            require(prior is None or prior["status"] in ("completed", "failed", "forgotten"),
                    "Pending memory update must be reconciled before another write")
            record = {"action": "learn", "status": "starting", "started_at": utc_now()}
            records[self.key] = record
            state.setdefault("memory_history", []).append(record)
            self.journal.save(state)
            def remember(value):
                record.update(value)
                self.journal.save(state)
            try:
                result = self.memory.learn_fixture(remember)
                record.update({"status": "completed", "result": result, "completed_at": utc_now()})
                self.journal.save(state)
                return record
            except Exception as exc:
                record.update({"status": "reconcile-required", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise

    def reconcile(self) -> dict:
        with self.journal.locked() as state:
            record = state["memory_updates"][self.key]
            if record["status"] in ("completed", "failed", "forgotten"):
                return record
            require(record["action"] == "learn",
                    "Deletion outcome is uncertain; establish writer quiescence before another mutation")
            require(record.get("update_id"),
                    "Memory submission outcome is unknown; do not replay or guess an operation ID")
            value = self.memory.read_update(record["update_id"])
            if value["status"] == "completed":
                result = self.memory.finish_update(value, record["before_watermark"])
                record.update({"status": "completed", "result": result, "completed_at": utc_now()})
            elif value["status"] == "failed":
                record.update({"status": "failed", "completed_at": utc_now(),
                               "error_digest": fingerprint(value.get("error"))})
            elif value["status"] == "superseded":
                record.update({"status": "reconcile-required",
                               "blocking": "Another update superseded this operation; writer quiescence is unverified"})
            else:
                record["status"] = "pending"
            self.journal.save(state)
            return record

    def forget(self) -> dict:
        with self.journal.locked() as state:
            prior = state.setdefault("memory_updates", {}).get(self.key)
            require(prior is None or prior["status"] in ("completed", "failed", "forgotten"),
                    "Pending native extraction could recreate deleted memories; reconcile first")
            record = {"action": "forget", "status": "started", "scope_key": self.key, "started_at": utc_now()}
            state["memory_updates"][self.key] = record
            state.setdefault("memory_history", []).append(record)
            self.journal.save(state)
            try:
                record.update({"result": self.memory.forget(), "status": "forgotten", "completed_at": utc_now()})
                self.journal.save(state)
                return record
            except Exception as exc:
                record.update({"status": "reconcile-required", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise
