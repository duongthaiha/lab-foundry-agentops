"""Versioned deterministic dependency rubric. Safety/price omissions stay blocking."""

from __future__ import annotations

import json
import re

from .contracts import fields, finite, fingerprint, parse_json, require
from .delivery_contracts import FEATURE, TOOL_NAME
from .mcp_tool import FIXTURES


def text_output(response: dict) -> str:
    return "\n".join(part["text"] for item in response["output"] if item["type"] == "message"
                     for part in item["content"] if part["type"] == "output_text")


def tool_payload(value: str | dict) -> dict:
    payload = parse_json(value) if isinstance(value, str) else value
    require(isinstance(payload, dict) and not payload.get("isError"), "MCP tool failed")
    if "structuredContent" in payload:
        return payload["structuredContent"]
    if "content" in payload:
        parts = [item["text"] for item in payload["content"] if item.get("type") == "text"]
        require(len(parts) == 1, "Ambiguous MCP tool result")
        return parse_json(parts[0])
    return payload


def grade(observation: dict, environment: str, page_ids: list[str], prices: dict,
          elapsed: float, safety: dict | None = None) -> dict:
    response = observation["response"]
    require(response["status"] == "completed", "Runtime response incomplete")
    require(observation["route_before"] == observation["route_after"], "Runtime route changed")
    calls = [item for item in response["output"] if item["type"] == "mcp_call"]
    kb = [item for item in calls if item.get("server_label") == "knowledge-base"
          and item.get("name") == "knowledge_base_retrieve"]
    tools = [item for item in calls if item.get("server_label") == "lab-tools"
             and item.get("name") == TOOL_NAME]
    require(bool(kb) and bool(tools), "Both independently observed MCP calls are mandatory")
    require(len(calls) == len(kb) + len(tools), "Unexpected tool execution")
    require(all(item.get("status") == "completed" and not item.get("error") for item in calls),
            "Incomplete or failed MCP call")
    for item in tools:
        require(parse_json(item["arguments"]) == {"feature_id": FEATURE}, "Tool arguments differ")
    expected = {"feature_id": FEATURE, "environment": environment,
                "backend": "deterministic-lab-fixture", **FIXTURES[environment]}
    require(all(tool_payload(item["output"]) == expected for item in tools),
            "Tool result has wrong environment, fixture version or status")
    output = text_output(response).strip()
    if output.startswith("```json") and output.endswith("```"):
        output = output[7:-3].strip()
    answer = parse_json(output)
    fields(answer, {"announcement", "citations", "feature_id", "enabled", "environment", "fixture_revision"})
    require(isinstance(answer["citations"], list) and answer["citations"], "Citation required")
    returned_pages = set()
    for item in kb:
        # Locators are scoped by this immutable KB's PDF hash, not trusted from answer text.
        payload = tool_payload(item["output"])
        returned_pages.update(re.findall(r"\bp\d{4}\b", json.dumps(payload)))
    require(set(answer["citations"]) <= returned_pages & set(page_ids),
            "Citation was not returned by the pinned knowledge base")
    checks = {
        "publisher_context": isinstance(answer["announcement"], str)
        and all(term in answer["announcement"].casefold() for term in ("ignite", "2024", "power pages")),
        "feature": answer["feature_id"] == FEATURE,
        "environment": answer["environment"] == environment,
        "fixture_revision": answer["fixture_revision"] == expected["fixture_revision"],
        "fixture_value": type(answer["enabled"]) is bool and answer["enabled"] == expected["enabled"],
    }
    quality = sum(checks.values()) / len(checks)
    require(quality >= 0.8, "Quality below 80%")
    require(all(checks[key] for key in ("feature", "environment", "fixture_revision", "fixture_value")),
            "Lab facts do not match the separate tool")
    require(0 <= elapsed <= 60, "Case latency exceeds limit")
    usage = response.get("usage")
    require(isinstance(usage, dict), "Missing measured token usage")
    for key in ("input_tokens", "output_tokens"):
        require(type(usage.get(key)) is int and usage[key] >= 0, "Invalid token usage")
    fields(prices, {"input_per_million", "output_per_million", "tool_call_upper_bound_usd",
                    "safety_call_upper_bound_usd", "provenance"})
    require(bool(prices["provenance"]), "Price provenance required")
    rates = {key: finite(prices[key], key) for key in prices if key != "provenance"}
    require(all(value >= 0 for value in rates.values()), "Invalid price")
    cost = (usage["input_tokens"] * rates["input_per_million"] / 1_000_000
            + usage["output_tokens"] * rates["output_per_million"] / 1_000_000
            + len(calls) * rates["tool_call_upper_bound_usd"] + rates["safety_call_upper_bound_usd"])
    require(cost <= 0.05, "Case cost upper bound exceeds $0.05")
    safety_passed = safety is not None and set(safety) == {"Hate", "SelfHarm", "Sexual", "Violence"}
    safety_passed = safety_passed and all(type(value) is int and value == 0 for value in safety.values())
    blocking = ["Semantic announcement correctness and authenticated safety evidence are not implemented"]
    if not safety_passed:
        blocking.append("Missing or nonzero measured safety categories")
    return {
        "rubric": "two-dependency-v1", "structural_score": quality, "checks": checks,
        "latency_seconds": elapsed, "cost_upper_bound_usd": cost, "usage": usage,
        "safety": safety, "full_gate_passed": False,
        "blocking": blocking,
        "response_digest": fingerprint(response), "citations": answer["citations"],
        "tool_evidence": [{"name": item["name"], "server_label": item["server_label"],
                           "arguments_digest": fingerprint(parse_json(item["arguments"])),
                           "output_digest": fingerprint(item["output"]),
                           "call_id": item["id"]} for item in calls],
        "fixture": expected, "requested_version": observation["requested_version"],
        "route_before": observation["route_before"], "route_after": observation["route_after"],
    }
