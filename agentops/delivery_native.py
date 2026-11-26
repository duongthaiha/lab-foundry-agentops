"""Native version selection and candidate invocation, never a proxy serving pointer."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from azure.ai.projects.models import VersionRefIndicator
from azure.core.exceptions import ResourceNotFoundError

from .contracts import ENVIRONMENTS, digest_value, fields, fingerprint, instant, require, utc_now
from .delivery_azure import project_shape
from .delivery_contracts import validate


def runtime_of(definition: dict) -> str:
    if definition["kind"] == "hosted":
        return "hosted"
    require(definition["kind"] == "prompt", "Unsupported native runtime")
    harness = definition.get("harness")
    if not harness:
        return "prompt"
    require(harness["type"] == "microsoft_copilot_preview", "Unexpected managed harness")
    return "harness"


def selected(details: dict) -> str:
    rules = details["agent_endpoint"]["version_selector"]["version_selection_rules"]
    require(len(rules) == 1 and rules[0]["type"] == "FixedRatio"
            and rules[0]["traffic_percentage"] == 100, "Native selector must be pinned, not latest or split")
    version = rules[0]["agent_version"]
    require(isinstance(version, str) and version.isdigit(), "Regular numeric version required")
    return version


def identity(details: dict) -> str:
    principal = details.get("instance_identity", {}).get("principal_id")
    require(isinstance(principal, str) and principal, "Native runtime identity is missing")
    return fingerprint({"principal_id": principal})


class NativeRuntime:
    def __init__(self, foundry, check_write: Callable[[], None]):
        self.foundry = foundry
        self.agents = foundry.client.agents
        self.check_write = check_write

    def snapshot(self, name: str) -> dict:
        details = self.foundry.get_agent(name)
        require(details is not None, "A reviewed serving baseline must be provisioned first")
        require(details["state"] == "enabled" and details["configuration_state"] == "enabled"
                and details["instance_identity"].get("status") == "active", "Native agent or identity is not enabled")
        return {"version": selected(details), "identity_digest": identity(details),
                "endpoint_digest": fingerprint(details["agent_endpoint"])}

    def candidate(self, name: str, definition: dict, metadata: dict, previous: dict) -> dict:
        """The prior selector is checked before/after creation, never moved to test a candidate."""
        require(self.snapshot(name) == previous, "Serving changed before candidate creation")
        baseline = self.foundry.get_version(name, previous["version"])
        require(runtime_of(baseline["definition"]) == runtime_of(definition), "Runtime changes require another agent")
        matches = [v.as_dict() for v in self.agents.list_versions(name, include_drafts=True)
                   if v.as_dict().get("metadata") == metadata]
        require(len(matches) <= 1, "Ambiguous candidate creation; reconcile instead of retrying")
        if matches:
            candidate = matches[0]
        else:
            self.check_write()
            candidate = self.agents.create_version(
                name, body={"definition": definition, "metadata": metadata, "draft": False},
                headers={"Foundry-Features": "MicrosoftCopilot=V1Preview"},
            ).as_dict()
        require(self.snapshot(name) == previous, "Creating the candidate changed native serving")
        require(candidate.get("draft", False) is False and candidate["status"] == "active",
                "Candidate is not an active regular version; reconcile before evaluation")
        require(candidate["metadata"] == metadata and
                project_shape(candidate["definition"], definition) == definition, "Candidate read-back differs")
        require(candidate["version"] != previous["version"], "Candidate is the serving baseline")
        return candidate

    def session(self, name: str, version: str, on_created: Callable[[dict], None]) -> dict:
        self.check_write()
        created = self.agents.create_session(
            agent_name=name, version_indicator=VersionRefIndicator(agent_version=version)).as_dict()
        session_id = created["agent_session_id"]
        on_created({"name": name, "version": version, "session_id": session_id})
        deadline = time.monotonic() + 300
        while True:
            actual = self.agents.get_session(name, session_id).as_dict()
            require(actual["version_indicator"] == {"type": "version_ref", "agent_version": version},
                    "Hosted session is bound to another version")
            if actual["status"] == "active":
                return actual
            require(actual["status"] in ("creating", "updating") and time.monotonic() < deadline,
                    "Hosted session activation failed or exceeded five minutes")
            time.sleep(1)

    def invoke_version(self, name: str, version: str, runtime: str, question: str,
                       digest: str, expected_serving: dict, on_session: Callable[[dict], None]) -> dict:
        before = self.snapshot(name)
        require(before == expected_serving, "Serving drift before exact-version invocation")
        kwargs = {"input": question, "max_output_tokens": 1024, "metadata": {"release_digest": digest}}
        session = None
        if runtime == "hosted":
            session = self.session(name, version, on_session)
            kwargs["extra_body"] = {"agent_session_id": session["agent_session_id"]}
        else:
            kwargs["extra_body"] = {"agent_reference": {
                "type": "agent_reference", "name": name, "version": version}}
        client_args = {} if runtime == "prompt" else {"agent_name": name}
        with self.foundry.client.get_openai_client(**client_args, max_retries=0, timeout=60) as client:
            self.check_write()
            conversation = client.conversations.create()
            kwargs["conversation"] = conversation.id
            if runtime == "harness":
                kwargs["extra_headers"] = {"Foundry-Features": "MicrosoftCopilot=V1Preview"}
            self.check_write()
            started = time.monotonic()
            response = client.responses.create(**kwargs).model_dump(mode="json")
            elapsed = time.monotonic() - started
        after = self.snapshot(name)
        require(after == before, "Serving drift during candidate invocation")
        require(response["status"] == "completed", "Native response incomplete")
        reference = response.get("agent_reference")
        require(isinstance(reference, dict) and reference.get("name") == name
                and reference.get("version") == version,
                "Service did not confirm the requested candidate version; no cutover is allowed")
        if session is not None:
            require(response.get("agent_session_id") == session["agent_session_id"],
                    "Response was not produced by the version-bound Hosted session")
            actual = self.agents.get_session(name, session["agent_session_id"]).as_dict()
            require(actual["version_indicator"] == session["version_indicator"], "Hosted session version changed")
        return {"response": response, "requested_version": version, "route_before": before,
                "route_after": after, "identity_digest": after["identity_digest"],
                "conversation_id": conversation.id, "session": session, "latency_seconds": elapsed,
                "native_candidate_contract_verified": runtime != "harness",
                "observed_at": utc_now()}

    def cutover(self, name: str, version: str, previous: dict) -> dict:
        require(self.snapshot(name) == previous, "Native serving changed before cutover")
        target = self.foundry.get_version(name, version)
        require(target["status"] == "active" and not target.get("draft", False), "Unservable target")
        self.check_write()
        self.agents.update_details(name, body={"agent_endpoint": {"version_selector": {
            "version_selection_rules": [{"type": "FixedRatio", "agent_version": version, "traffic_percentage": 100}],
        }}})
        after = self.snapshot(name)
        require(after["version"] == version and after["identity_digest"] == previous["identity_digest"],
                "Native cutover read-back failed; reconcile before any retry")
        return after

    def drain_owned_session(self, name: str, session_id: str, version: str) -> None:
        try:
            session = self.agents.get_session(name, session_id).as_dict()
        except ResourceNotFoundError:
            return
        require(session["version_indicator"] == {"type": "version_ref", "agent_version": version},
                "Refusing to drain a session bound to an unexpected version")
        self.check_write()
        self.agents.delete_session(name, session_id)
        deadline = time.monotonic() + 300
        while True:
            try:
                state = self.agents.get_session(name, session_id).as_dict()["status"]
            except ResourceNotFoundError:
                return
            if state in ("deleted", "expired"):
                return
            require(state == "deleting" and time.monotonic() < deadline, "Session drain did not complete")
            time.sleep(1)


class NativeDelivery:
    """Participating writers across all environments must share one journal/lease."""

    def __init__(self, runtime: NativeRuntime, journal, inspect_context: Callable[[dict], dict], environment: str):
        require(environment in ENVIRONMENTS, "Unknown delivery environment")
        self.runtime, self.journal, self.inspect_context = runtime, journal, inspect_context
        self.runtime.check_write = self.journal.check
        self.environment = environment

    def _state(self, state: dict) -> dict:
        return state.setdefault("native", {}).setdefault(self.environment, {
            "candidates": {}, "history": [], "retained": {}, "serving": {},
        })

    def _context(self, definition: dict) -> dict:
        context = self.inspect_context(definition)
        fields(context, {"components_digest", "content_digest", "state_digest", "identity_digest", "policy_digest"})
        for key, value in context.items():
            digest_value(value, key)
        return context

    def evaluate(self, bundle: dict, digest: str, definition: dict, evaluator: Callable[[dict], dict]) -> dict:
        validate(bundle)
        require(fingerprint(bundle) == digest, "Release digest mismatch")
        name = bundle["agent"]
        with self.journal.locked() as state:
            native = self._state(state)
            before = self.runtime.snapshot(name)
            context = self._context(definition)
            previous_definition = self.runtime.foundry.get_version(name, before["version"])["definition"]
            previous_context = self._context(previous_definition)
            attempt = {"action": "evaluate", "release_digest": digest, "before": before,
                       "started_at": utc_now(), "status": "started", "owned_sessions": []}
            native["candidates"].pop(digest, None)
            native["history"].append(attempt)
            self.journal.save(state)
            try:
                version = self.runtime.candidate(
                    name, definition, {"release_digest": digest, "purpose": "candidate"}, before)
                self.journal.check()
                def remember_session(session):
                    attempt["owned_sessions"].append(session)
                    self.journal.save(state)
                observations = [self.runtime.invoke_version(
                    name, version["version"], bundle["runtime"], question, digest, before, remember_session)
                    for question in bundle["evaluation"]["questions"]]
                self.journal.check()
                grades = [evaluator(item) for item in observations]
                require(self._context(definition) == context, "Dependency/content/state context changed during evaluation")
                require(self._context(previous_definition) == previous_context, "Retained baseline context drift")
                after = self.runtime.snapshot(name)
                require(after == before, "Serving moved during evaluation")
                record = {"release_digest": digest, "name": name, "runtime": bundle["runtime"],
                          "version": version["version"], "definition_digest": fingerprint(definition),
                          "definition": definition, "previous_definition": previous_definition,
                          "previous_context": previous_context,
                          "context": context, "before": before, "after": after,
                          "evaluated_at": utc_now(), "grades": grades,
                          "passed": all(item.get("full_gate_passed") is True for item in grades)
                          and all(item["native_candidate_contract_verified"] for item in observations),
                          "blocking": [] if bundle["runtime"] != "harness" else [
                              "Harness candidate override is unverified; an echoed version reference alone is not proof"],
                          "owned_sessions": attempt["owned_sessions"]}
                native["candidates"][digest] = record
                attempt.update({"status": "passed" if record["passed"] else "rejected",
                                "version": version["version"], "after": after})
                self.journal.save(state)
                return record
            except Exception as exc:
                attempt.update({"status": "failed", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise

    def promote(self, digest: str, serving_check: Callable[[dict], dict],
                upstream_check: Callable[[str, dict], dict]) -> dict:
        with self.journal.locked() as state:
            native = self._state(state)
            candidate = native["candidates"][digest]
            require(candidate["passed"] is True and candidate["grades"], "Exact candidate did not pass")
            age = (datetime.now(timezone.utc) - instant(candidate["evaluated_at"])).total_seconds()
            require(0 <= age <= 3600, "Evaluation is stale or from the future")
            require(self._context(candidate["definition"]) == candidate["context"], "Dependency/content/state evidence is stale")
            require(self._context(candidate["previous_definition"]) == candidate["previous_context"],
                    "Retained baseline context changed")
            actual = self.runtime.foundry.get_version(candidate["name"], candidate["version"])
            require(fingerprint(project_shape(actual["definition"], candidate["definition"]))
                    == candidate["definition_digest"], "Candidate definition changed after evaluation")
            index = ENVIRONMENTS.index(self.environment)
            if index:
                upstream_environment = ENVIRONMENTS[index - 1]
                receipt = state["native"].get(upstream_environment, {}).get("serving", {}).get(candidate["name"])
                require(receipt and receipt["release_digest"] == digest,
                        "Previous environment has not promoted this immutable release")
                require(upstream_check(upstream_environment, receipt) == receipt["after"],
                        "Previous environment no longer serves the verified release")
            current = self.runtime.snapshot(candidate["name"])
            receipt = native["serving"].get(candidate["name"])
            if receipt and receipt["release_digest"] == digest and receipt["after"] == current:
                return receipt
            require(current == candidate["before"], "Native serving changed since evaluation")
            attempt = {"action": "promote", "release_digest": digest, "status": "started",
                       "before": candidate["before"], "started_at": utc_now()}
            native["history"].append(attempt)
            native["retained"][candidate["name"]] = {
                "previous": candidate["before"], "target_version": candidate["version"],
                "previous_context": candidate["previous_context"],
                "previous_definition": candidate["previous_definition"],
                "current_context": candidate["context"], "current_definition": candidate["definition"],
                "release_digest": digest, "previous_receipt": native["serving"].get(candidate["name"]),
            }
            self.journal.save(state)
            try:
                after = self.runtime.cutover(candidate["name"], candidate["version"], candidate["before"])
                self.journal.check()
                observed = serving_check({**candidate, "serving": after})
                require(observed.get("version") == candidate["version"]
                        and observed.get("identity_digest") == after["identity_digest"],
                        "Consumer did not confirm the selected version and identity")
                require(self._context(candidate["definition"]) == candidate["context"], "Context changed during cutover")
                attempt.update({"status": "promoted", "after": after, "consumer": observed})
                native["serving"][candidate["name"]] = attempt
                self.journal.save(state)
                return attempt
            except Exception as exc:
                # A failed serving verification is a recoverable uncertainty, not a success.
                attempt.update({"status": "reconcile-required", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise

    def rollback(self, name: str, serving_check: Callable[[dict], dict]) -> dict:
        with self.journal.locked() as state:
            native = self._state(state)
            retained = native["retained"][name]
            require(self._context(retained["previous_definition"]) == retained["previous_context"]
                    and self._context(retained["current_definition"]) == retained["current_context"],
                    "Rollback needs content/state reconciliation; never restore stale state blindly")
            before = self.runtime.snapshot(name)
            require(before["version"] in (retained["target_version"], retained["previous"]["version"])
                    and before["identity_digest"] == retained["previous"]["identity_digest"],
                    "Another native release or identity is serving; do not overwrite it")
            attempt = {"action": "rollback", "status": "started", "before": before}
            native["history"].append(attempt)
            self.journal.save(state)
            try:
                after = before if before["version"] == retained["previous"]["version"] else self.runtime.cutover(
                    name, retained["previous"]["version"], before)
                self.journal.check()
                observed = serving_check({"name": name, "serving": after})
                require(observed.get("version") == after["version"]
                        and observed.get("identity_digest") == after["identity_digest"], "Rollback consumer mismatch")
                require(self._context(retained["previous_definition"]) == retained["previous_context"],
                        "Retained context changed during rollback")
                if retained["previous_receipt"] is not None:
                    require(retained["previous_receipt"]["after"] == after, "Restored release differs from retained receipt")
                    native["serving"][name] = retained["previous_receipt"]
                else:
                    native["serving"].pop(name, None)
                attempt.update({"status": "rolled-back", "after": after, "consumer": observed})
                self.journal.save(state)
                return attempt
            except Exception as exc:
                attempt.update({"status": "reconcile-required", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise

    def drain(self, name: str, session_id: str) -> dict:
        with self.journal.locked() as state:
            native = self._state(state)
            owned = [session for attempt in native["history"] for session in attempt.get("owned_sessions", [])
                     if session["name"] == name and session["session_id"] == session_id]
            require(len(owned) == 1, "Session ownership is missing or ambiguous")
            attempt = {"action": "drain", "session_id": session_id, "status": "started", "started_at": utc_now()}
            native["history"].append(attempt)
            self.journal.save(state)
            try:
                self.runtime.drain_owned_session(name, session_id, owned[0]["version"])
                self.journal.check()
                attempt.update({"status": "drained", "completed_at": utc_now()})
                self.journal.save(state)
                return attempt
            except Exception as exc:
                attempt.update({"status": "reconcile-required", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise
