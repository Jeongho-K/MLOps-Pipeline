"""Unit tests for G4 Canary Gate."""

from __future__ import annotations

from unittest.mock import patch

from src.orchestration.tasks.canary_gate import check_canary_gate


class TestCheckCanaryGate:
    """Tests for check_canary_gate (G4 gate)."""

    @patch("src.orchestration.tasks.canary_gate.query_p99_latency")
    @patch("src.orchestration.tasks.canary_gate.query_error_rate")
    def test_passes_with_good_metrics(
        self, mock_error: object, mock_latency: object
    ) -> None:
        mock_error.side_effect = [0.01, 0.01]  # champion, canary  # type: ignore[attr-defined]
        mock_latency.side_effect = [0.1, 0.1]  # champion, canary  # type: ignore[attr-defined]

        result = check_canary_gate.fn(
            prometheus_url="http://prom:9090",
        )
        assert result["passed"] is True
        assert "passed" in result["reason"].lower()

    @patch("src.orchestration.tasks.canary_gate.query_p99_latency")
    @patch("src.orchestration.tasks.canary_gate.query_error_rate")
    def test_fails_on_absolute_error_rate(
        self, mock_error: object, mock_latency: object
    ) -> None:
        mock_error.side_effect = [0.01, 0.10]  # champion, canary (10% error)  # type: ignore[attr-defined]
        mock_latency.side_effect = [0.1, 0.1]  # type: ignore[attr-defined]

        result = check_canary_gate.fn(
            prometheus_url="http://prom:9090",
            absolute_max_error_rate=0.05,
        )
        assert result["passed"] is False
        assert "absolute" in result["reason"].lower()

    @patch("src.orchestration.tasks.canary_gate.query_p99_latency")
    @patch("src.orchestration.tasks.canary_gate.query_error_rate")
    def test_fails_on_high_error_ratio(
        self, mock_error: object, mock_latency: object
    ) -> None:
        mock_error.side_effect = [0.01, 0.02]  # 2x ratio  # type: ignore[attr-defined]
        mock_latency.side_effect = [0.1, 0.1]  # type: ignore[attr-defined]

        result = check_canary_gate.fn(
            prometheus_url="http://prom:9090",
            max_error_rate_ratio=1.5,
        )
        assert result["passed"] is False
        assert "error rate ratio" in result["reason"].lower()

    @patch("src.orchestration.tasks.canary_gate.query_p99_latency")
    @patch("src.orchestration.tasks.canary_gate.query_error_rate")
    def test_fails_on_high_latency_ratio(
        self, mock_error: object, mock_latency: object
    ) -> None:
        mock_error.side_effect = [0.01, 0.01]  # type: ignore[attr-defined]
        mock_latency.side_effect = [0.1, 0.2]  # 2x ratio  # type: ignore[attr-defined]

        result = check_canary_gate.fn(
            prometheus_url="http://prom:9090",
            max_latency_ratio=1.3,
        )
        assert result["passed"] is False
        assert "latency ratio" in result["reason"].lower()

    @patch("src.orchestration.tasks.canary_gate.query_p99_latency")
    @patch("src.orchestration.tasks.canary_gate.query_error_rate")
    def test_passes_when_canary_data_insufficient(
        self, mock_error: object, mock_latency: object
    ) -> None:
        mock_error.side_effect = [0.01, None]  # canary has no data  # type: ignore[attr-defined]
        mock_latency.side_effect = [0.1, None]  # type: ignore[attr-defined]

        result = check_canary_gate.fn(
            prometheus_url="http://prom:9090",
        )
        assert result["passed"] is True
        assert "insufficient" in result["reason"].lower()

    @patch("src.orchestration.tasks.canary_gate.query_p99_latency")
    @patch("src.orchestration.tasks.canary_gate.query_error_rate")
    def test_passes_when_champion_error_is_zero(
        self, mock_error: object, mock_latency: object
    ) -> None:
        """When champion has 0 errors, skip ratio check but still check absolute."""
        mock_error.side_effect = [0.0, 0.01]  # type: ignore[attr-defined]
        mock_latency.side_effect = [0.1, 0.12]  # type: ignore[attr-defined]

        result = check_canary_gate.fn(
            prometheus_url="http://prom:9090",
        )
        assert result["passed"] is True
