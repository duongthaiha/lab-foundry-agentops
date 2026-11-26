"""Release-local native toolbox snapshots; never publish a mutable shared default."""

from __future__ import annotations

from copy import deepcopy
from itertools import islice
import re
from typing import Callable

from azure.core.exceptions import ResourceNotFoundError

from .contracts import ENVIRONMENTS, digest_value, fields, fingerprint, require, utc_now
from .delivery_azure import project_shape
from .delivery_contracts import TOOL_NAME, endpoint
from .delivery_knowledge import MCP_API


class NativeToolbox:
    def __init__(self, foundry, check_write: Callable[[], None]):
        self.api = foundry.client.toolboxes
        self.target = foundry.target
        self.project_endpoint = endpoint(self.target["project_endpoint"], "services.ai.azure.com", project=True)
        self.check_write = check_write

    @staticmethod
    def name(digest: str) -> str:
        digest_value(digest, "release digest")
        return "contoso-tools-" + digest[:20]

    def desired(self, digest: str, tools: list[dict], policy_id: str) -> dict:
        self.name(digest)
        account_id, separator, project_name = self.target["project_resource_id"].rpartition("/projects/")
        require(separator and project_name and policy_id == account_id + "/raiPolicies/Microsoft.DefaultV2",
                "Explicit account-local Microsoft.DefaultV2 policy binding required")
        require(len(tools) == 2, "Exactly the IQ and lab MCP integrations are required")
        expected = {"knowledge-base": "knowledge_base_retrieve", "lab-tools": TOOL_NAME}
        require({item.get("server_label") for item in tools} == set(expected), "Unexpected toolbox server labels")
        for item in tools:
            fields(item, {"type", "server_label", "server_url", "allowed_tools",
                          "require_approval", "project_connection_id"})
            label = item["server_label"]
            require(item["type"] == "mcp" and item["allowed_tools"] == [expected[label]]
                    and item["require_approval"] == "never"
                    and item["project_connection_id"] == f"{label}-{digest[:20]}",
                    "Toolbox must retain the release-local read-only MCP binding")
            if label == "lab-tools":
                require(item["server_url"] == self.target["tool_mcp_url"] + "/releases/" + digest,
                        "Toolbox fixture endpoint is not release-bound")
            else:
                prefix = self.target["search_endpoint"] + "/knowledgebases/"
                suffix = f"/mcp?api-version={MCP_API}"
                require(item["server_url"].startswith(prefix) and item["server_url"].endswith(suffix)
                        and re.fullmatch(r"kb-[0-9a-f]{20}", item["server_url"][len(prefix):-len(suffix)]),
                        "Toolbox IQ endpoint is outside the environment")
        return {"description": "Release-local IQ and synthetic read-only lab tools",
                "tools": deepcopy(tools), "skills": [],
                "policies": {"rai_config": {"rai_policy_name": policy_id}},
                "metadata": {"release_digest": digest, "purpose": "release-local-tools"}}

    def _single_version(self, name: str) -> dict:
        versions = list(islice(self.api.list_versions(name, limit=2), 2))
        require(len(versions) == 1, "Release-local toolbox is missing or has multiple versions; reconcile")
        return versions[0].as_dict()

    def _verify_shape(self, actual: dict, desired: dict, name: str):
        require(actual["name"] == name, "Toolbox response belongs to another resource")
        require(isinstance(actual["version"], str) and actual["version"].isdigit(),
                "Numeric toolbox version required")
        require(project_shape(actual, desired) == desired, "Immutable toolbox definition drift")
        require(actual["policies"] == desired["policies"], "Toolbox policy configuration drift")
        for observed, configured in zip(actual["tools"], desired["tools"]):
            require(all(value is None or value == {} or value == []
                        for key, value in observed.items() if key not in configured),
                    "Unexpected toolbox capability or authentication override")

    def ensure(self, digest: str, tools: list[dict], policy_id: str) -> dict:
        name, desired = self.name(digest), self.desired(digest, tools, policy_id)
        try:
            self.api.get(name)
        except ResourceNotFoundError:
            self.check_write()
            created = self.api.create_version(name, body=desired).as_dict()
            self._verify_shape(created, desired, name)
        return self.read_existing(digest, tools, policy_id)

    def read_existing(self, digest: str, tools: list[dict], policy_id: str) -> dict:
        name, desired = self.name(digest), self.desired(digest, tools, policy_id)
        actual = self._single_version(name)
        self._verify_shape(actual, desired, name)
        details = self.api.get(name).as_dict()
        require(details["name"] == name and details["default_version"] == actual["version"],
                "Release-local toolbox default drift; never republish to repair it")
        receipt = {"release_digest": digest, "name": name, "version": actual["version"],
                   "definition_digest": fingerprint(desired),
                   "mcp_endpoint": self._endpoint(name, actual["version"])}
        self.verify(digest, tools, policy_id, receipt)
        return receipt

    def _endpoint(self, name: str, version: str) -> str:
        return f"{self.project_endpoint}/toolboxes/{name}/versions/{version}/mcp?api-version=v1"

    def verify(self, digest: str, tools: list[dict], policy_id: str, receipt: dict) -> None:
        name, desired = self.name(digest), self.desired(digest, tools, policy_id)
        fields(receipt, {"release_digest", "name", "version", "definition_digest", "mcp_endpoint"})
        version = receipt["version"]
        require(isinstance(version, str) and version.isdigit(), "Pinned numeric toolbox version required")
        require(receipt == {"release_digest": digest, "name": name, "version": version,
                            "definition_digest": fingerprint(desired),
                            "mcp_endpoint": self._endpoint(name, version)}, "Toolbox receipt binding drift")
        listed = self._single_version(name)
        require(listed["version"] == version, "Release-local toolbox version changed")
        actual = self.api.get_version(name, version).as_dict()
        self._verify_shape(actual, desired, name)
        details = self.api.get(name).as_dict()
        require(details["name"] == name and details["default_version"] == version,
                "Release-local toolbox default changed; retained consumers must not be republished")

    def inspect_reference(self, digest: str, version: str | None = None) -> dict:
        """Read-only reference resolution, not evidence that a runtime invoked the toolbox."""
        name = self.name(digest)
        details = self.api.get(name).as_dict()
        require(details["name"] == name, "Toolbox response belongs to another resource")
        selected = details["default_version"] if version is None else version
        require(isinstance(selected, str) and selected.isdigit(), "Numeric toolbox version required")
        actual = self.api.get_version(name, selected).as_dict()
        require(actual["name"] == name and actual["version"] == selected, "Toolbox version read-back differs")
        after = self.api.get(name).as_dict()
        require(after["name"] == name and after["default_version"] == details["default_version"],
                "Toolbox default changed during reference inspection")
        return {"name": name, "version": selected, "default_version": after["default_version"],
                "pinned": version is not None, "definition_digest": fingerprint({
                    key: actual.get(key) for key in ("tools", "skills", "policies", "metadata")}),
                "runtime_invocation_verified": False}


class ToolboxDelivery:
    """Journal uncertain creation; reconciliation is read-only and cannot resubmit."""

    def __init__(self, toolbox: NativeToolbox, journal, environment: str):
        require(environment in ENVIRONMENTS, "Unknown toolbox environment")
        self.toolbox, self.journal, self.environment = toolbox, journal, environment
        self.toolbox.check_write = journal.check

    def _records(self, state: dict) -> dict:
        return state.setdefault("toolboxes", {}).setdefault(self.environment, {})

    def ensure(self, digest: str, tools: list[dict], policy_id: str) -> dict:
        binding = fingerprint(self.toolbox.desired(digest, tools, policy_id))
        with self.journal.locked() as state:
            records = self._records(state)
            if digest in records:
                record = records[digest]
                require(record["binding_digest"] == binding, "Toolbox operation intent changed")
                require(record["status"] == "ready", "Pending toolbox creation; reconcile without replaying it")
                self.toolbox.verify(digest, tools, policy_id, record["receipt"])
                return record["receipt"]
            record = {"binding_digest": binding, "status": "started", "started_at": utc_now()}
            records[digest] = record
            self.journal.save(state)
            try:
                receipt = self.toolbox.ensure(digest, tools, policy_id)
                record.update({"status": "ready", "receipt": receipt, "completed_at": utc_now()})
                self.journal.save(state)
                return receipt
            except Exception as exc:
                record.update({"status": "reconcile-required", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise

    def reconcile(self, digest: str, tools: list[dict], policy_id: str) -> dict:
        binding = fingerprint(self.toolbox.desired(digest, tools, policy_id))
        with self.journal.locked() as state:
            record = self._records(state)[digest]
            require(record["binding_digest"] == binding, "Toolbox operation intent changed")
            receipt = self.toolbox.read_existing(digest, tools, policy_id)
            record.update({"status": "ready", "receipt": receipt, "reconciled_at": utc_now()})
            record.pop("error_type", None)
            self.journal.save(state)
            return receipt
