"""Unit tests for Evidently drift detection."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.core.monitoring.evidently.config import DriftConfig
from src.core.monitoring.evidently.drift_detector import (
    build_dataframe_from_logs,
    check_drift_threshold,
    detect_drift,
    push_drift_metrics,
)


class TestDriftConfig:
    """Tests for DriftConfig defaults and environment variable overrides."""

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DriftConfig provides expected default values (credentials from env)."""
        monkeypatch.setenv("DRIFT_S3_ACCESS_KEY", "testkey")
        monkeypatch.setenv("DRIFT_S3_SECRET_KEY", "testsecret")
        cfg = DriftConfig()
        assert cfg.s3_endpoint == "http://minio:9000"
        assert cfg.s3_access_key == "testkey"
        assert cfg.s3_secret_key == "testsecret"
        assert cfg.prediction_logs_bucket == "prediction-logs"
        assert cfg.drift_reports_bucket == "drift-reports"
        assert cfg.reference_path == "reference/baseline.jsonl"
        assert cfg.lookback_days == 1
        assert cfg.pushgateway_url == "http://pushgateway:9091"

    def test_override_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables with DRIFT_ prefix override defaults."""
        monkeypatch.setenv("DRIFT_S3_ACCESS_KEY", "testkey")
        monkeypatch.setenv("DRIFT_S3_SECRET_KEY", "testsecret")
        monkeypatch.setenv("DRIFT_S3_ENDPOINT", "http://custom-minio:9000")
        monkeypatch.setenv("DRIFT_LOOKBACK_DAYS", "7")
        monkeypatch.setenv("DRIFT_PUSHGATEWAY_URL", "http://my-gateway:9091")

        cfg = DriftConfig()
        assert cfg.s3_endpoint == "http://custom-minio:9000"
        assert cfg.lookback_days == 7
        assert cfg.pushgateway_url == "http://my-gateway:9091"
        assert cfg.s3_access_key == "testkey"


class TestBuildDataframe:
    """Tests for build_dataframe_from_logs."""

    def test_parses_jsonl_lines(self) -> None:
        """Correctly parses multi-line JSONL into a DataFrame."""
        lines = [
            {"confidence": 0.9, "label": "cat"},
            {"confidence": 0.7, "label": "dog"},
            {"confidence": 0.5, "label": "cat"},
        ]
        raw = "\n".join(json.dumps(row) for row in lines)
        df = build_dataframe_from_logs(raw)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert list(df.columns) == ["confidence", "label"]
        assert df["confidence"].tolist() == [0.9, 0.7, 0.5]

    def test_empty_input_returns_empty_dataframe(self) -> None:
        """Empty or blank input returns an empty DataFrame."""
        assert build_dataframe_from_logs("").empty
        assert build_dataframe_from_logs("   ").empty
        assert build_dataframe_from_logs("\n\n").empty

    def test_skips_blank_lines(self) -> None:
        """Blank lines interspersed in JSONL are skipped."""
        raw = '\n{"a": 1}\n\n{"a": 2}\n'
        df = build_dataframe_from_logs(raw)
        assert len(df) == 2

    def test_skips_malformed_lines(self) -> None:
        """Malformed JSON lines are skipped, valid lines are kept (within 10% threshold)."""
        # 1 bad line out of 20 total = 5% malformed, below 10% threshold
        good_lines = [json.dumps({"a": i}) for i in range(19)]
        raw = "\n".join(good_lines[:10] + ["NOT_JSON"] + good_lines[10:])
        df = build_dataframe_from_logs(raw)
        assert len(df) == 19

    def test_raises_on_high_malformed_ratio(self) -> None:
        """Raises ValueError when more than 10% of lines are malformed."""
        # 9 bad lines + 1 good = 90% malformed
        lines = ["BAD"] * 9 + ['{"a": 1}']
        raw = "\n".join(lines)
        with pytest.raises(ValueError, match="Too many malformed JSON lines"):
            build_dataframe_from_logs(raw)


class TestDetectDrift:
    """Tests for detect_drift using Evidently Report."""

    @staticmethod
    def _make_df(loc: float, n: int = 60) -> pd.DataFrame:
        """Create a DataFrame with two numeric columns drawn from N(loc, 1)."""
        rng = np.random.default_rng(42)
        return pd.DataFrame(
            {
                "feature_a": rng.normal(loc, 1, n),
                "feature_b": rng.normal(loc, 1, n),
            }
        )

    def test_result_structure(self) -> None:
        """detect_drift always returns the required keys."""
        df = self._make_df(0.0)
        result = detect_drift(df, df.copy())

        assert "drift_detected" in result
        assert "drift_score" in result
        assert "column_drifts" in result
        assert isinstance(result["drift_detected"], bool)
        assert isinstance(result["drift_score"], float)
        assert isinstance(result["column_drifts"], dict)

    def test_no_drift_on_identical_data(self) -> None:
        """Identical reference and current data should not trigger drift."""
        df = self._make_df(0.0)
        result = detect_drift(df, df.copy())

        # drift_score should be low (0 or very low) for identical distributions
        assert result["drift_score"] == 0.0
        assert result["drift_detected"] is False

    def test_drift_on_shifted_data(self) -> None:
        """Heavily shifted data should trigger drift detection."""
        reference = self._make_df(0.0, n=60)
        current = self._make_df(10.0, n=60)  # very different distribution
        result = detect_drift(reference, current)

        assert result["drift_detected"] is True
        assert result["drift_score"] > 0.0
        assert "feature_a" in result["column_drifts"]
        assert "feature_b" in result["column_drifts"]

    def test_column_drifts_are_floats(self) -> None:
        """Per-column drift values should be floats."""
        reference = self._make_df(0.0, n=60)
        current = self._make_df(10.0, n=60)
        result = detect_drift(reference, current)

        for col, score in result["column_drifts"].items():
            assert isinstance(score, float), f"column_drifts[{col!r}] should be float"


class TestPushDriftMetrics:
    """Tests for push_drift_metrics."""

    def test_pushes_metrics_to_gateway(self) -> None:
        """push_drift_metrics calls push_to_gateway with correct arguments."""
        with patch("src.core.monitoring.evidently.drift_detector.push_to_gateway") as mock_push:
            push_drift_metrics(
                pushgateway_url="http://pushgateway:9091",
                drift_detected=True,
                drift_score=0.75,
            )

        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args
        assert call_kwargs.args[0] == "http://pushgateway:9091"
        assert call_kwargs.kwargs["job"] == "evidently_drift"

    def test_pushes_no_drift(self) -> None:
        """push_drift_metrics works correctly when drift is not detected."""
        with patch("src.core.monitoring.evidently.drift_detector.push_to_gateway") as mock_push:
            push_drift_metrics(
                pushgateway_url="http://pushgateway:9091",
                drift_detected=False,
                drift_score=0.0,
            )

        mock_push.assert_called_once()

    def test_registry_is_isolated(self) -> None:
        """Each call uses a fresh CollectorRegistry (no global state leakage)."""
        registries: list[MagicMock] = []

        with patch("src.core.monitoring.evidently.drift_detector.push_to_gateway") as mock_push:

            def capture_registry(*args, **kwargs) -> None:
                registries.append(kwargs.get("registry"))

            mock_push.side_effect = capture_registry

            push_drift_metrics("http://gw:9091", drift_detected=True, drift_score=0.5)
            push_drift_metrics("http://gw:9091", drift_detected=False, drift_score=0.0)

        assert len(registries) == 2
        # Registries from separate calls should be distinct objects
        assert registries[0] is not registries[1]


class TestCheckDriftThreshold:
    """Tests for check_drift_threshold quality gate function."""

    @staticmethod
    def _mock_drift_result(drift_score: float = 0.2) -> dict[str, object]:
        """Create a mock detect_drift return value."""
        return {
            "drift_detected": drift_score > 0.0,
            "drift_score": drift_score,
            "column_drifts": {"feature_a": 0.05, "feature_b": 0.01},
        }

    def test_pass_when_below_threshold(self) -> None:
        """Returns passed=True when drift_score is below drift_share_threshold."""
        ref = pd.DataFrame({"a": [1, 2, 3]})
        cur = pd.DataFrame({"a": [1, 2, 3]})

        with patch(
            "src.core.monitoring.evidently.drift_detector.detect_drift",
            return_value=self._mock_drift_result(drift_score=0.1),
        ):
            result = check_drift_threshold(ref, cur, drift_share_threshold=0.3)

        assert result["passed"] is True

    def test_fail_when_above_threshold(self) -> None:
        """Returns passed=False when drift_score exceeds drift_share_threshold."""
        ref = pd.DataFrame({"a": [1, 2, 3]})
        cur = pd.DataFrame({"a": [1, 2, 3]})

        with patch(
            "src.core.monitoring.evidently.drift_detector.detect_drift",
            return_value=self._mock_drift_result(drift_score=0.5),
        ):
            result = check_drift_threshold(ref, cur, drift_share_threshold=0.3)

        assert result["passed"] is False

    def test_boundary_equal_to_threshold_fails(self) -> None:
        """Drift score exactly equal to threshold should fail (strict < comparison)."""
        ref = pd.DataFrame({"a": [1, 2, 3]})
        cur = pd.DataFrame({"a": [1, 2, 3]})

        with patch(
            "src.core.monitoring.evidently.drift_detector.detect_drift",
            return_value=self._mock_drift_result(drift_score=0.3),
        ):
            result = check_drift_threshold(ref, cur, drift_share_threshold=0.3)

        assert result["passed"] is False

    def test_return_dict_has_all_keys(self) -> None:
        """Return dict contains all 5 expected keys."""
        ref = pd.DataFrame({"a": [1, 2, 3]})
        cur = pd.DataFrame({"a": [1, 2, 3]})

        with patch(
            "src.core.monitoring.evidently.drift_detector.detect_drift",
            return_value=self._mock_drift_result(drift_score=0.1),
        ):
            result = check_drift_threshold(ref, cur)

        expected_keys = {"passed", "drift_score", "drift_detected", "column_drifts", "threshold"}
        assert set(result.keys()) == expected_keys

    def test_custom_threshold_is_applied(self) -> None:
        """Non-default threshold is correctly applied and returned."""
        ref = pd.DataFrame({"a": [1, 2, 3]})
        cur = pd.DataFrame({"a": [1, 2, 3]})

        with patch(
            "src.core.monitoring.evidently.drift_detector.detect_drift",
            return_value=self._mock_drift_result(drift_score=0.4),
        ):
            result = check_drift_threshold(ref, cur, drift_share_threshold=0.5)

        assert result["passed"] is True
        assert result["threshold"] == 0.5
