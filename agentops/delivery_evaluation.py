"""Versioned deterministic dependency rubric. Safety/price omissions stay blocking."""

from __future__ import annotations

import json
import re
from uuid import UUID

from .contracts import LabError, fields, finite, fingerprint, parse_json, require
from .delivery_contracts import ANSWER_SCHEMA, FEATURE, TOOL_NAME
from .mcp_tool import FIXTURES


def text_output(response: dict) -> str:
    return "\n".join(part["text"] for item in response["output"] if item["type"] == "message"
                     for part in item["content"] if part["type"] == "output_text")


def judged_text(response: dict) -> str:
    """Answer text without runtime citation markers, which url_citation annotations carry separately."""
    parts = []
    for item in response["output"]:
        if item["type"] != "message":
            continue
        for part in item["content"]:
            if part["type"] != "output_text":
                continue
            value = part["text"]
            spans = [(row.get("start_index"), row.get("end_index")) for row in part.get("annotations") or []
                     if row.get("type") == "url_citation"]
            require(all(type(start) is int and type(stop) is int for start, stop in spans),
                    "Invalid citation annotation")
            limit = len(value)
            for start, stop in sorted(spans, reverse=True):
                require(0 <= start < stop <= limit, "Invalid citation annotation")
                # Only exact 【...】 markers are removed; an annotated span of answer text stays judged.
                if re.fullmatch(r"\u3010[^\u3010\u3011]*\u3011", value[start:stop]):
                    value = value[:start].rstrip(" ") + value[stop:]
                limit = start
            parts.append(value)
    return "\n".join(parts)


def rendered_output(value: str):
    try:
        return parse_json(value)
    except LabError:
        # Foundry renders structured MCP results as the text content followed by
        # {"structuredResponse": structuredContent}; accept only two identical copies.
        try:
            _, end = json.JSONDecoder().raw_decode(value)
        except json.JSONDecodeError as exc:
            raise LabError("Invalid MCP tool output") from exc
        content, structured = parse_json(value[:end]), parse_json(value[end:])
        require(isinstance(structured, dict) and set(structured) == {"structuredResponse"}
                and structured["structuredResponse"] == content, "Ambiguous MCP tool result")
        return content


def tool_payload(value: str | dict) -> dict:
    payload = rendered_output(value) if isinstance(value, str) else value
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
    require(all(item["type"] in ("mcp_call", "mcp_list_tools", "message", "reasoning")
                for item in response["output"]), "Unexpected runtime capability executed")
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
    principals = []
    for item in tools:
        payload = tool_payload(item["output"])
        fields(payload, set(expected), {"_auth"})
        require({key: payload[key] for key in expected} == expected,
                "Tool result has wrong environment, fixture version or status")
        if "_auth" in payload:
            auth = payload["_auth"]
            fields(auth, {"principal_digest", "trace_id"}, {"release_digest"})
            require(isinstance(auth["principal_digest"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", auth["principal_digest"]) is not None,
                    "Invalid authenticated principal digest")
            require(isinstance(auth["trace_id"], str), "Invalid tool trace ID")
            require(str(UUID(auth["trace_id"])) == auth["trace_id"], "Invalid tool trace ID")
            if "release_digest" in auth:
                require(isinstance(auth["release_digest"], str)
                        and re.fullmatch(r"[0-9a-f]{64}", auth["release_digest"]) is not None
                        and auth["release_digest"] == observation.get("release_digest"),
                        "MCP release binding differs from the candidate")
            principals.append(auth)
    output = text_output(response).strip()
    if output.startswith("```json") and output.endswith("```"):
        output = output[7:-3].strip()
    answer = parse_json(output)
    fields(answer, set(ANSWER_SCHEMA["required"]))
    require(isinstance(answer["citations"], list) and answer["citations"], "Citation required")
    require(all(isinstance(value, str) and re.fullmatch(r"p[0-9]{4}", value)
                for value in answer["citations"]), "Citation IDs must be typed page locators")
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
    if len(principals) != len(tools):
        blocking.append("Missing authenticated tool caller evidence")
    if len(principals) != len(tools) or any("release_digest" not in value for value in principals):
        blocking.append("Missing release-bound MCP transport evidence")
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
        "authenticated_tool_calls": principals,
        "route_before": observation["route_before"], "route_after": observation["route_after"],
    }
