"""Native version selection and candidate invocation, never a proxy serving pointer."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from azure.ai.projects.models import VersionRefIndicator
from azure.core.exceptions import ResourceNotFoundError

from .contracts import ENVIRONMENTS, digest_value, fields, fingerprint, instant, require, utc_now
from .delivery_azure import project_shape
from .delivery_contracts import MAX_OUTPUT_TOKENS, validate


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
        # The live service may omit identity status; operational `state` already reflects
        # identity- or blueprint-derived disablement, and an explicit non-active status still fails.
        instance = details.get("instance_identity") or {}
        require(details["state"] == "enabled" and details["configuration_state"] == "enabled"
                and instance.get("status", "active") == "active", "Native agent or identity is not enabled")
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
        kwargs = {"input": question, "max_output_tokens": MAX_OUTPUT_TOKENS, "metadata": {"release_digest": digest}}
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
                "release_digest": digest,
                "conversation_id": conversation.id, "session": session, "latency_seconds": elapsed,
                "native_candidate_contract_verified": runtime != "harness",
                "observed_at": utc_now()}

    def invoke_serving(self, name: str, question: str, operation_digest: str, expected: dict,
                       on_conversation: Callable[[str], None], on_session: Callable[[dict], None]) -> dict:
        """Observe the native selector, never request the expected version or an existing session."""
        digest_value(operation_digest, "operation release digest")
        before = self.snapshot(name)
        require(before == expected, "Serving drift before consumer invocation")
        version = self.foundry.get_version(name, before["version"])
        runtime = runtime_of(version["definition"])
        kwargs = {"input": question, "max_output_tokens": MAX_OUTPUT_TOKENS,
                  "metadata": {"operation_release_digest": operation_digest, "verification": "native-serving"}}
        if runtime == "harness":
            kwargs["extra_headers"] = {"Foundry-Features": "MicrosoftCopilot=V1Preview"}
        with self.foundry.client.get_openai_client(agent_name=name, max_retries=0, timeout=60) as client:
            self.check_write()
            conversation = client.conversations.create()
            on_conversation(conversation.id)
            self.check_write()
            started = time.monotonic()
            response = client.responses.create(conversation=conversation.id, **kwargs).model_dump(mode="json")
            elapsed = time.monotonic() - started
        reference = response.get("agent_reference")
        actual_version = reference.get("version") if isinstance(reference, dict) else None
        session_id = response.get("agent_session_id")
        if runtime == "hosted" and isinstance(session_id, str) and session_id:
            # Preserve the returned handle even if subsequent read-back or version checks fail.
            on_session({"name": name, "version": actual_version, "session_id": session_id})
        require(response.get("status") == "completed" and isinstance(response.get("id"), str)
                and response["id"], "Serving response incomplete or missing its service ID")
        require(isinstance(reference, dict) and reference.get("name") == name
                and actual_version == before["version"],
                "Consumer response did not confirm the native serving version")
        if runtime == "hosted":
            require(isinstance(session_id, str) and session_id, "Consumer response has no Hosted session binding")
            session = self.agents.get_session(name, session_id).as_dict()
            require(session.get("status") == "active" and session.get("agent_session_id") == session_id
                    and session.get("version_indicator") == {"type": "version_ref", "agent_version": actual_version},
                    "Consumer Hosted session is not active on the serving version")
        after = self.snapshot(name)
        require(after == before, "Serving drift during consumer invocation")
        return {"version": actual_version, "identity_digest": after["identity_digest"],
                "identity_source": "agent-control-plane", "route_before": before, "route_after": after,
                "response_id": response["id"], "conversation_id": conversation.id,
                "session_id": session_id if runtime == "hosted" else None,
                "operation_release_digest": operation_digest, "latency_seconds": elapsed,
                "observed_at": utc_now(), "selection": "native-endpoint-without-override"}

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
        require(isinstance(version, str) and version.isdigit(),
                "Unknown owned session version; reconcile before drain")
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

    def __init__(self, runtime: NativeRuntime, journal, inspect_context: Callable[[dict], dict] | None,
                 environment: str):
        require(environment in ENVIRONMENTS, "Unknown delivery environment")
        self.runtime, self.journal, self.inspect_context = runtime, journal, inspect_context
        self.runtime.check_write = self.journal.check
        self.environment = environment

    def _state(self, state: dict) -> dict:
        return state.setdefault("native", {}).setdefault(self.environment, {
            "candidates": {}, "history": [], "retained": {}, "serving": {},
        })

    def _context(self, definition: dict) -> dict:
        require(self.inspect_context is not None, "Authenticated context inspection is required for delivery")
        context = self.inspect_context(definition)
        fields(context, {"components_digest", "content_digest", "state_digest", "identity_digest", "policy_digest"})
        for key, value in context.items():
            digest_value(value, key)
        return context

    def _consumer(self, name: str, question: str, digest: str, serving: dict, attempt: dict, state: dict) -> dict:
        def remember_conversation(conversation_id):
            attempt.setdefault("consumer_conversations", []).append(conversation_id)
            self.journal.save(state)

        def remember_session(session):
            owned = [item["session_id"] for row in self._state(state)["history"]
                     for item in row.get("owned_sessions", [])]
            require(session["session_id"] not in owned, "Fresh consumer reused an owned Hosted session")
            attempt.setdefault("owned_sessions", []).append(session)
            self.journal.save(state)

        return self.runtime.invoke_serving(name, question, digest, serving, remember_conversation, remember_session)

    def verify_serving(self, bundle: dict, digest: str) -> dict:
        """A protected consumer diagnostic, not release evaluation or permission to promote."""
        validate(bundle)
        require(fingerprint(bundle) == digest, "Release digest mismatch")
        name = bundle["agent"]
        with self.journal.locked() as state:
            native = self._state(state)
            before = self.runtime.snapshot(name)
            actual = self.runtime.foundry.get_version(name, before["version"])
            require(runtime_of(actual["definition"]) == bundle["runtime"], "Serving runtime differs from the release")
            attempt = {"action": "verify-serving", "operation_release_digest": digest,
                       "status": "started", "before": before, "started_at": utc_now()}
            native["history"].append(attempt)
            self.journal.save(state)
            try:
                observed = self._consumer(name, bundle["evaluation"]["questions"][0], digest, before, attempt, state)
                attempt.update({"status": "serving-verified", "consumer": observed,
                                "release_validated": False, "full_gate_passed": False, "completed_at": utc_now()})
                self.journal.save(state)
                return attempt
            except Exception as exc:
                attempt.update({"status": "reconcile-required", "error_type": type(exc).__name__})
                self.journal.save(state)
                raise

    def evaluate(self, bundle: dict, digest: str, definition: dict, evaluator: Callable[[dict], dict]) -> dict:
        validate(bundle)
        require(fingerprint(bundle) == digest, "Release digest mismatch")
        require(runtime_of(definition) == bundle["runtime"], "Candidate runtime differs from the release")
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
                attempt["consumer_before"] = self._consumer(
                    name, bundle["evaluation"]["questions"][0], digest, before, attempt, state)
                self.journal.save(state)
                version = self.runtime.candidate(
                    name, definition, {"release_digest": digest, "purpose": "candidate"}, before)
                self.journal.check()
                def remember_session(session):
                    attempt["owned_sessions"].append(session)
                    self.journal.save(state)
                observations = [self.runtime.invoke_version(
                    name, version["version"], bundle["runtime"], question, digest, before, remember_session)
                    for question in bundle["evaluation"]["questions"]]
                attempt["consumer_during"] = self._consumer(
                    name, bundle["evaluation"]["questions"][0], digest, before, attempt, state)
                self.journal.save(state)
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
                          "consumer_question": bundle["evaluation"]["questions"][0],
                          "consumer_before": attempt["consumer_before"], "consumer_during": attempt["consumer_during"],
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

    def promote(self, digest: str, upstream_check: Callable[[str, dict], dict]) -> dict:
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
                "consumer_question": candidate["consumer_question"],
                "release_digest": digest, "previous_receipt": native["serving"].get(candidate["name"]),
            }
            self.journal.save(state)
            try:
                after = self.runtime.cutover(candidate["name"], candidate["version"], candidate["before"])
                self.journal.check()
                observed = self._consumer(candidate["name"], candidate["consumer_question"],
                                          digest, after, attempt, state)
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

    def rollback(self, name: str) -> dict:
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
                observed = self._consumer(name, retained["consumer_question"],
                                          retained["release_digest"], after, attempt, state)
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
