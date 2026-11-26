"""Native scoped-memory primitives with explicit retention/migration limitations."""

from __future__ import annotations

from datetime import timedelta
from typing import Callable
from uuid import UUID

from azure.ai.projects.models import (
    MemorySearchOptions, MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions,
)
from azure.core.exceptions import ResourceNotFoundError

from .contracts import fingerprint, identifier, require, utc_now
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
        self.api, self.store, self.scope = project.beta.memory_stores, store, caller_oid

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
        remember_operation({"status": "pending", "continuation_token": poller.continuation_token()})
        value = poller.result(timeout=300)
        require(poller.done(), "Native memory update exceeded five minutes; remote operation may continue, reconcile before retrying")
        require(value["status"] == "completed" and value.get("result"), "Native memory update did not complete")
        require(all(operation["memory_item"]["scope"] == self.scope
                    for operation in value["result"]["memory_operations"]), "Memory update crossed caller scope")
        require(value["result"].get("usage") is not None, "Native memory usage was not returned")
        after = self.snapshot()
        require(after["count"] > 0, "No native memory was extracted")
        return {"before_watermark": before["watermark"], "after_watermark": after["watermark"],
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
