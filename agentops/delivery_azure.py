"""Azure boundaries for the operator. No provisioning, role grants or login fallbacks."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import LabError, canonical, parse_json, require
from .delivery_contracts import MAX_OUTPUT_TOKENS


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LabError("Redirect refused; credentials must remain at the configured origin")


class AzureHTTP:
    def __init__(self, credential, origin: str, scope: str):
        self.credential, self.origin, self.scope = credential, origin.rstrip("/"), scope

    def request(self, method: str, path: str, body: dict | None = None, *,
                absent_ok: bool = False, headers: dict | None = None) -> dict | None:
        require(path.startswith("/") and not path.startswith("//"), "Relative service path required")
        token = self.credential.get_token(self.scope).token
        request = Request(self.origin + path, method=method,
                          data=canonical(body) if body is not None else None,
                          headers={"Authorization": "Bearer " + token,
                                   "Content-Type": "application/json", **(headers or {})})
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                require(len(data) <= 8 * 1024 * 1024, "Oversized service response")
                return parse_json(data) if data else {}
        except HTTPError as exc:
            exc.close()
            if absent_ok and exc.code == 404:
                return None
            # Service bodies/URLs can contain source text, tenant IDs and credentials.
            raise LabError(f"Azure request rejected (HTTP {exc.code}); inspect private service telemetry") from exc
        except (URLError, TimeoutError) as exc:
            raise LabError("Azure request outcome uncertain; reconcile before retrying mutations") from exc


def project_shape(actual: Any, desired: Any) -> Any:
    """Compare explicitly configured fields, excluding documented server defaults."""
    if isinstance(desired, dict):
        require(isinstance(actual, dict) and desired.keys() <= actual.keys(), "Missing read-back fields")
        return {key: project_shape(actual[key], value) for key, value in desired.items()}
    if isinstance(desired, list):
        require(isinstance(actual, list) and len(actual) == len(desired), "Read-back list differs")
        return [project_shape(left, right) for left, right in zip(actual, desired)]
    return actual


def ensure(http: AzureHTTP, path: str, desired: dict, expected: dict | None = None) -> dict:
    """Create once; `expected` omits request fields the service is known to normalize."""
    expected = desired if expected is None else expected
    existing = http.request("GET", path, absent_ok=True)
    if existing is None:
        http.request("PUT", path, desired, headers={"If-None-Match": "*"})
        existing = http.request("GET", path)
    require(project_shape(existing, expected) == expected, "Immutable resource read-back drift")
    return existing


class BlobJournal:
    """One leased/CAS blob coordinates all participating writers in an environment."""

    def __init__(self, account_url: str, credential):
        from azure.storage.blob import BlobClient

        self.blob = BlobClient(account_url, "release-locks", "delivery-state.json",
                               credential=credential, retry_total=0, connection_timeout=10,
                               read_timeout=30)
        self.lease = None
        self.etag = None
        self.failure: Exception | None = None

    @contextmanager
    def locked(self):
        from azure.core.exceptions import AzureError, ResourceExistsError

        try:
            try:
                self.blob.upload_blob(canonical({"schema_version": 1, "candidates": {}, "serving": {},
                                                 "history": [], "retained": []}), overwrite=False)
            except ResourceExistsError:
                pass
            self.lease = self.blob.acquire_lease(lease_duration=60)
        except AzureError:
            self.blob.close()
            raise
        stopped = threading.Event()

        def renew():
            while not stopped.wait(15):
                try:
                    self.lease.renew()
                except Exception as exc:
                    # Preserve the failure for the foreground writer; never continue silently.
                    self.failure = exc
                    return

        worker = threading.Thread(target=renew, name="delivery-lease", daemon=True)
        worker.start()
        try:
            download = self.blob.download_blob(lease=self.lease)
            self.etag = download.properties.etag
            state = parse_json(download.readall())
            require(state["schema_version"] == 1, "Unknown delivery journal")
            yield state
        finally:
            stopped.set()
            worker.join(timeout=35)
            try:
                if self.failure is None:
                    self.lease.release()
            finally:
                self.lease = None
                self.blob.close()
            require(not worker.is_alive(), "Lease worker did not stop")
            if self.failure is not None:
                raise LabError("Distributed lease lost; mutation outcome requires reconciliation") from self.failure

    def check(self):
        from azure.core.exceptions import AzureError

        require(self.lease is not None and self.failure is None, "No valid distributed lease")
        try:
            self.lease.renew()
        except AzureError as exc:
            self.failure = exc
            raise LabError("Distributed lease lost; no further mutation is allowed") from exc

    def save(self, state: dict):
        from azure.core import MatchConditions

        self.check()
        result = self.blob.upload_blob(canonical(state), overwrite=True, lease=self.lease,
                                       etag=self.etag, match_condition=MatchConditions.IfNotModified)
        self.etag = result["etag"]


class Foundry:
    def __init__(self, target: dict, credential):
        from azure.ai.projects import AIProjectClient

        self.target = target
        self.client = AIProjectClient(target["project_endpoint"], credential, allow_preview=True,
                                      retry_total=0, connection_timeout=10, read_timeout=30)
        self.arm = AzureHTTP(credential, "https://management.azure.com",
                             "https://management.azure.com/.default")
        self.search = AzureHTTP(credential, target["search_endpoint"], "https://search.azure.com/.default")

    def close(self):
        self.client.close()

    def get_agent(self, name: str) -> dict | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.client.agents.get(name).as_dict()
        except ResourceNotFoundError:
            return None

    def create_dependency_probe(self, name: str, definition: dict, metadata: dict) -> dict:
        existing = self.get_agent(name)
        if existing is not None:
            versions = list(self.client.agents.list_versions(name, include_drafts=True))
            require(len(versions) == 1, "Release-local agent was mutated or creation is ambiguous")
            version = versions[0].as_dict()
        else:
            version = self.client.agents.create_version(
                name, body={"definition": definition, "metadata": metadata, "draft": False},
                headers={"Foundry-Features": "MicrosoftCopilot=V1Preview"},
            ).as_dict()
        require(version["metadata"] == metadata and version.get("draft", False) is False,
                "Probe metadata or draft mismatch")
        require(project_shape(version["definition"], definition) == definition,
                "Probe definition differs")
        require(version["status"] == "active", "Probe is not active; reconcile before evaluating")
        selector = {"version_selector": {"version_selection_rules": [{
            "type": "FixedRatio", "agent_version": version["version"], "traffic_percentage": 100,
        }]}, "protocol_configuration": {"responses": {}}}
        self.client.agents.update_details(name, body={"agent_endpoint": selector})
        readback = self.get_agent(name)
        require(project_shape(readback["agent_endpoint"], selector) == selector, "Probe route is not pinned")
        return version

    def get_version(self, name: str, version: str) -> dict:
        return self.client.agents.get_version(name, version).as_dict()

    def invoke(self, name: str, version: str, question: str, runtime: str, digest: str) -> dict:
        before = self.get_agent(name)
        rules = before["agent_endpoint"]["version_selector"]["version_selection_rules"]
        require(rules == [{"type": "FixedRatio", "agent_version": version, "traffic_percentage": 100}],
                "Runtime endpoint version drift")
        # A release-local agent has one regular version and an explicitly pinned endpoint.
        # This avoids an undocumented draft/version query parameter for the harness.
        with self.client.get_openai_client(agent_name=name, max_retries=0, timeout=60) as client:
            conversation = client.conversations.create()
            response = client.responses.create(
                conversation=conversation.id, input=question, max_output_tokens=MAX_OUTPUT_TOKENS,
                metadata={"release_digest": digest},
                extra_headers={"Foundry-Features": "MicrosoftCopilot=V1Preview"},
            )
            result = response.model_dump(mode="json")
        after = self.get_agent(name)
        require(after["agent_endpoint"] == before["agent_endpoint"], "Endpoint changed during invocation")
        return {"response": result, "requested_version": version, "route_before": rules,
                "route_after": rules, "conversation_id": conversation.id,
                "runtime": runtime, "release_digest": digest,
                "observed_at": datetime.now(timezone.utc).isoformat()}
