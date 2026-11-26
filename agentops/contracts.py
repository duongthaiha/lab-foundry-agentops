"""Strict, portable contracts shared by the local release controls."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENVIRONMENTS = ("dev", "test", "labprod")
RUNTIMES = ("prompt", "hosted", "harness")
COMPONENT_KINDS = ("toolbox", "knowledge", "memory-policy")
FORBIDDEN_KEYS = {
    "password", "secret", "token", "api_key", "connection_string",
    "subscription_id", "tenant_id", "resource_id", "endpoint", "records",
    "user_scope", "environment",
}


class LabError(ValueError):
    """An explicit contract, gate, or capability rejection."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        # Private diagnostics for protected evidence only; public logs print just the message.
        self.detail = detail or {}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LabError(message)


def key_names(keys, limit: int = 10) -> list[str]:
    """Sorted identifier-like key names, so diagnostics never echo arbitrary payload text."""
    names = sorted(key if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", key)
                   else "<non-identifier>" for key in keys)
    return names[:limit]


def fields(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    require(isinstance(value, dict), "Expected a JSON object")
    require(required <= value.keys(), "Missing required fields: " + ", ".join(sorted(required - value.keys())))
    unexpected = value.keys() - (required | (optional or set()))
    if unexpected:
        raise LabError("Unexpected fields in object",
                       {"unexpected_fields": key_names(unexpected), "unexpected_count": len(unexpected)})


def text(value: Any, field: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{field} must be nonempty text")
    return value


def identifier(value: Any, field: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,62}", value) is not None,
            f"{field} must be a lowercase identifier")
    return value


def digest_value(value: Any, field: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            f"{field} must be a SHA-256 hex digest")
    return value


def finite(value: Any, field: str) -> float:
    require(type(value) in (int, float), f"{field} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise LabError(f"{field} must be finite") from exc
    require(math.isfinite(result), f"{field} must be finite")
    return result


def canonical(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LabError("Value cannot be represented as canonical JSON") from exc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value: Any) -> str:
    return sha256(canonical(value))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON object key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise LabError("Non-finite JSON constant")


def parse_json(data: str | bytes) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LabError("Invalid UTF-8 JSON") from exc


def read_json(path: Path) -> Any:
    return parse_json(path.read_bytes())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def instant(value: Any) -> datetime:
    text(value, "timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LabError("Invalid ISO timestamp") from exc
    require(result.tzinfo is not None, "Timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def portable(value: Any) -> None:
    if isinstance(value, dict):
        require(not ({key.lower().replace("-", "_") for key in value} & FORBIDDEN_KEYS),
                "Environment, state, or secret fields in portable input")
        for child in value.values():
            portable(child)
    elif isinstance(value, list):
        for child in value:
            portable(child)
    elif isinstance(value, str):
        require("/subscriptions/" not in value.lower(), "Azure resource IDs are not portable")
    elif type(value) is float:
        finite(value, "portable number")


def component(value: Any) -> None:
    fields(value, {"name", "kind", "version", "owner", "compatibility", "configuration"})
    identifier(value["name"], "component name")
    require(value["kind"] in COMPONENT_KINDS, "Unsupported component kind")
    for key in ("version", "owner", "compatibility"):
        text(value[key], key)
    require(isinstance(value["configuration"], dict), "Component configuration must be an object")
    portable(value)


def policy(value: Any) -> None:
    fields(value, {"evidence_type", "max_age_seconds", "thresholds"})
    require(value["evidence_type"] == "simulated", "Only simulated evaluation policy is implemented")
    require(type(value["max_age_seconds"]) is int and value["max_age_seconds"] > 0,
            "Positive integer evaluation age required")
    fields(value["thresholds"], {"quality_min", "unsafe_max", "latency_ms_max", "cost_usd_max"})
    limits = value["thresholds"]
    for key in limits:
        require(finite(limits[key], key) >= 0, "Negative evaluation threshold")
    require(limits["quality_min"] <= 1 and limits["unsafe_max"] <= 1,
            "Quality and unsafe rates must be within [0, 1]")


def evidence_record(value: Any, category: str) -> None:
    fields(value, {"category", "evidence_type", "snapshots"})
    require(value["category"] == category and value["evidence_type"] == "simulated",
            "Wrong evidence category or type")
    require(isinstance(value["snapshots"], dict), "Snapshots must be an object")
    for name, digest in value["snapshots"].items():
        identifier(name, "snapshot name")
        digest_value(digest, "snapshot digest")
