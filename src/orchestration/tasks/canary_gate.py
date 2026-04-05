"""G4 Canary Gate — compare canary vs champion serving metrics.

Queries Prometheus for error rate and P99 latency from both
champion and canary containers, then applies ratio-based thresholds
to decide whether the canary deployment should proceed or roll back.
"""

from __future__ import annotations

import logging

from prefect import task
from prefect.artifacts import create_markdown_artifact

from src.monitoring.canary_metrics import query_error_rate, query_p99_latency

logger = logging.getLogger(__name__)


@task(name="check-canary-gate", retries=1, retry_delay_seconds=30)
def check_canary_gate(
    prometheus_url: str,
    champion_job: str = "api",
    canary_job: str = "api-canary",
    max_error_rate_ratio: float = 1.5,
    max_latency_ratio: float = 1.3,
    absolute_max_error_rate: float = 0.05,
    query_window: str = "5m",
) -> dict:
    """G4 Canary Gate: compare canary vs champion metrics.

    Args:
        prometheus_url: Prometheus server URL.
        champion_job: Prometheus job name for the champion container.
        canary_job: Prometheus job name for the canary container.
        max_error_rate_ratio: Max canary/champion error rate ratio.
        max_latency_ratio: Max canary/champion P99 latency ratio.
        absolute_max_error_rate: Hard ceiling for canary error rate.
        query_window: PromQL time window for rate calculations.

    Returns:
        Dict with keys: passed (bool), reason (str), metrics (dict).
    """
    champion_error = query_error_rate(prometheus_url, champion_job, query_window)
    canary_error = query_error_rate(prometheus_url, canary_job, query_window)
    champion_latency = query_p99_latency(prometheus_url, champion_job, query_window)
    canary_latency = query_p99_latency(prometheus_url, canary_job, query_window)

    metrics = {
        "champion_error_rate": champion_error,
        "canary_error_rate": canary_error,
        "champion_p99_latency": champion_latency,
        "canary_p99_latency": canary_latency,
    }

    logger.info("G4 metrics: %s", metrics)

    # Insufficient data — treat as pass (canary may not have enough traffic yet)
    if canary_error is None or canary_latency is None:
        logger.warning("G4: Insufficient canary metrics, skipping check")
        return {"passed": True, "reason": "Insufficient canary data", "metrics": metrics}

    # Check absolute error rate ceiling
    if canary_error > absolute_max_error_rate:
        reason = (
            f"Canary error rate {canary_error:.4f} exceeds "
            f"absolute max {absolute_max_error_rate:.4f}"
        )
        logger.warning("G4 FAIL: %s", reason)
        _create_gate_artifact(passed=False, reason=reason, metrics=metrics)
        return {"passed": False, "reason": reason, "metrics": metrics}

    # Check error rate ratio (only if champion has measurable error rate)
    if champion_error is not None and champion_error > 0:
        error_ratio = canary_error / champion_error
        if error_ratio > max_error_rate_ratio:
            reason = (
                f"Canary/champion error rate ratio {error_ratio:.2f} "
                f"exceeds max {max_error_rate_ratio:.2f}"
            )
            logger.warning("G4 FAIL: %s", reason)
            _create_gate_artifact(passed=False, reason=reason, metrics=metrics)
            return {"passed": False, "reason": reason, "metrics": metrics}

    # Check latency ratio (only if champion has measurable latency)
    if champion_latency is not None and champion_latency > 0:
        latency_ratio = canary_latency / champion_latency
        if latency_ratio > max_latency_ratio:
            reason = (
                f"Canary/champion P99 latency ratio {latency_ratio:.2f} "
                f"exceeds max {max_latency_ratio:.2f}"
            )
            logger.warning("G4 FAIL: %s", reason)
            _create_gate_artifact(passed=False, reason=reason, metrics=metrics)
            return {"passed": False, "reason": reason, "metrics": metrics}

    reason = "All G4 checks passed"
    logger.info("G4 PASS: %s", reason)
    _create_gate_artifact(passed=True, reason=reason, metrics=metrics)
    return {"passed": True, "reason": reason, "metrics": metrics}


def _create_gate_artifact(
    passed: bool,
    reason: str,
    metrics: dict,
) -> None:
    """Create a Prefect markdown artifact summarizing the G4 result."""
    status = "✅ PASSED" if passed else "❌ FAILED"
    md = f"## G4 Canary Gate — {status}\n\n"
    md += f"**Reason:** {reason}\n\n"
    md += "| Metric | Champion | Canary |\n"
    md += "|--------|----------|--------|\n"
    md += (
        f"| Error Rate | {_fmt(metrics.get('champion_error_rate'))} "
        f"| {_fmt(metrics.get('canary_error_rate'))} |\n"
    )
    md += (
        f"| P99 Latency | {_fmt(metrics.get('champion_p99_latency'))} "
        f"| {_fmt(metrics.get('canary_p99_latency'))} |\n"
    )
    create_markdown_artifact(key="g4-canary-gate", markdown=md)


def _fmt(value: float | None) -> str:
    """Format a metric value for display."""
    return f"{value:.4f}" if value is not None else "N/A"
