"""G5 Runtime Gate — classify drift severity and determine auto-response.

Evaluates drift detection results and classifies the severity
into LOW, MEDIUM, or HIGH, then returns the recommended action.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from prefect import task
from prefect.artifacts import create_markdown_artifact

logger = logging.getLogger(__name__)


class DriftSeverity(StrEnum):
    """Drift severity classification for G5 gate."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@task(name="evaluate-runtime-gate")
def evaluate_runtime_gate(
    drift_score: float,
    drift_detected: bool,
    low_threshold: float = 0.3,
    high_threshold: float = 0.6,
) -> dict:
    """G5 Runtime Gate: classify drift severity and determine response.

    Args:
        drift_score: Overall drift score from Evidently (0.0 to 1.0).
        drift_detected: Whether Evidently flagged drift.
        low_threshold: Drift score below this is LOW severity.
        high_threshold: Drift score at or above this is HIGH severity.

    Returns:
        Dict with keys: severity (str), action (str), drift_score (float).
    """
    if not drift_detected or drift_score < low_threshold:
        severity = DriftSeverity.LOW
        action = "log_only"
    elif drift_score < high_threshold:
        severity = DriftSeverity.MEDIUM
        action = "trigger_active_learning"
    else:
        severity = DriftSeverity.HIGH
        action = "rollback_and_retrain"

    result = {
        "severity": severity.value,
        "action": action,
        "drift_score": drift_score,
        "drift_detected": drift_detected,
    }

    logger.info(
        "G5 Runtime Gate: severity=%s, action=%s (drift_score=%.4f)",
        severity.value,
        action,
        drift_score,
    )

    _create_gate_artifact(result)
    return result


def _create_gate_artifact(result: dict) -> None:
    """Create a Prefect markdown artifact summarizing the G5 result."""
    severity = result["severity"].upper()
    action_map = {
        "log_only": "No action needed",
        "trigger_active_learning": "Trigger AL pipeline + retraining",
        "rollback_and_retrain": "Rollback to previous champion + retrain",
    }
    action_desc = action_map.get(result["action"], result["action"])

    markdown = f"""## G5 Runtime Gate — {severity}

| Metric | Value |
|--------|-------|
| Drift Score | {result['drift_score']:.4f} |
| Drift Detected | {result['drift_detected']} |
| Severity | {severity} |
| Action | {action_desc} |
"""
    create_markdown_artifact(key="g5-runtime-gate", markdown=markdown)
