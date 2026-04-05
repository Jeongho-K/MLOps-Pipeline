"""Unit tests for G5 Runtime Gate."""

from __future__ import annotations

from src.core.orchestration.tasks.runtime_gate import DriftSeverity, evaluate_runtime_gate


class TestEvaluateRuntimeGate:
    """Tests for evaluate_runtime_gate (G5 gate)."""

    def test_low_severity_when_no_drift(self) -> None:
        result = evaluate_runtime_gate.fn(
            drift_score=0.1,
            drift_detected=False,
        )
        assert result["severity"] == DriftSeverity.LOW.value
        assert result["action"] == "log_only"

    def test_low_severity_when_score_below_threshold(self) -> None:
        result = evaluate_runtime_gate.fn(
            drift_score=0.2,
            drift_detected=True,
            low_threshold=0.3,
        )
        assert result["severity"] == DriftSeverity.LOW.value
        assert result["action"] == "log_only"

    def test_medium_severity_triggers_active_learning(self) -> None:
        result = evaluate_runtime_gate.fn(
            drift_score=0.45,
            drift_detected=True,
            low_threshold=0.3,
            high_threshold=0.6,
        )
        assert result["severity"] == DriftSeverity.MEDIUM.value
        assert result["action"] == "trigger_active_learning"

    def test_high_severity_triggers_rollback(self) -> None:
        result = evaluate_runtime_gate.fn(
            drift_score=0.8,
            drift_detected=True,
            low_threshold=0.3,
            high_threshold=0.6,
        )
        assert result["severity"] == DriftSeverity.HIGH.value
        assert result["action"] == "rollback_and_retrain"

    def test_boundary_at_low_threshold(self) -> None:
        """Score exactly at low_threshold should be MEDIUM."""
        result = evaluate_runtime_gate.fn(
            drift_score=0.3,
            drift_detected=True,
            low_threshold=0.3,
            high_threshold=0.6,
        )
        assert result["severity"] == DriftSeverity.MEDIUM.value

    def test_boundary_at_high_threshold(self) -> None:
        """Score exactly at high_threshold should be HIGH."""
        result = evaluate_runtime_gate.fn(
            drift_score=0.6,
            drift_detected=True,
            low_threshold=0.3,
            high_threshold=0.6,
        )
        assert result["severity"] == DriftSeverity.HIGH.value

    def test_includes_metrics_in_result(self) -> None:
        result = evaluate_runtime_gate.fn(
            drift_score=0.5,
            drift_detected=True,
        )
        assert "drift_score" in result
        assert "drift_detected" in result
        assert result["drift_score"] == 0.5
