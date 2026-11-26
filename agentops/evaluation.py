"""Bind a completed evaluation to exactly one candidate and enforce its policy."""

from datetime import datetime, timezone
from typing import Any

from .contracts import fields, finite, instant, policy, require


def evaluate(candidate: dict[str, Any], report: Any, now: datetime | None = None) -> None:
    fields(report, {"evidence_type", "status", "context", "completed_at", "metrics"})
    require(report["evidence_type"] == "simulated", "Live evaluation evidence is not implemented")
    require(report["status"] == "completed", "Evaluation did not complete successfully")
    require(report["context"] == candidate["context"], "Evaluation context does not match exact candidate")
    policy(candidate["policy"])
    completed = instant(report["completed_at"])
    current = now or datetime.now(timezone.utc)
    require(instant(candidate["created_at"]) <= completed <= current, "Invalid evaluation time")
    require((current - completed).total_seconds() <= candidate["policy"]["max_age_seconds"],
            "Evaluation evidence is stale")
    fields(report["metrics"], {"quality", "unsafe", "latency_ms", "cost_usd"})
    metrics = {name: finite(value, name) for name, value in report["metrics"].items()}
    require(all(value >= 0 for value in metrics.values()), "Negative evaluation metric")
    require(metrics["quality"] <= 1 and metrics["unsafe"] <= 1, "Invalid quality or unsafe rate")
    limits = candidate["policy"]["thresholds"]
    for metric, threshold, lower in (
        ("quality", "quality_min", True), ("unsafe", "unsafe_max", False),
        ("latency_ms", "latency_ms_max", False), ("cost_usd", "cost_usd_max", False),
    ):
        passed = metrics[metric] >= limits[threshold] if lower else metrics[metric] <= limits[threshold]
        require(passed, f"Evaluation threshold failed: {metric}")
