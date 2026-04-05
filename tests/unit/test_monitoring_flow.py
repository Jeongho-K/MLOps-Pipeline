"""Unit tests for the monitoring pipeline flow and tasks."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from src.core.orchestration.flows.monitoring_flow import (
    fetch_prediction_logs,
    fetch_reference_data,
    run_drift_detection,
    upload_drift_report,
)


def _jsonl(*records: dict[str, Any]) -> bytes:
    """Encode records as JSONL bytes."""
    return "\n".join(json.dumps(r) for r in records).encode("utf-8")


class TestFetchPredictionLogs:
    """Tests for fetch_prediction_logs task."""

    def test_returns_dataframe_from_single_day(self) -> None:
        """Fetches JSONL objects for a single day and returns a DataFrame."""
        records = [
            {"predicted_class": "cat", "confidence": 0.9},
            {"predicted_class": "dog", "confidence": 0.7},
        ]

        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {"Contents": [{"Key": "2026-03-27/logs.jsonl"}]}
        mock_client.get_object.return_value = {"Body": BytesIO(_jsonl(*records))}

        with patch(
            "src.core.orchestration.flows.monitoring_flow.boto3.client",
            return_value=mock_client,
        ):
            df = fetch_prediction_logs.fn(
                s3_endpoint="http://minio:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                lookback_days=1,
            )

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "predicted_class" in df.columns
        assert "confidence" in df.columns

    def test_returns_empty_dataframe_when_no_objects(self) -> None:
        """Returns an empty DataFrame when no log objects are found."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {"Contents": []}

        with patch(
            "src.core.orchestration.flows.monitoring_flow.boto3.client",
            return_value=mock_client,
        ):
            df = fetch_prediction_logs.fn(
                s3_endpoint="http://minio:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                lookback_days=1,
            )

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_concatenates_multiple_days(self) -> None:
        """Concatenates JSONL from multiple days into a single DataFrame."""
        records_day1 = [{"predicted_class": "cat", "confidence": 0.9}]
        records_day2 = [{"predicted_class": "dog", "confidence": 0.8}]

        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = [
            {"Contents": [{"Key": "2026-03-27/logs.jsonl"}]},
            {"Contents": [{"Key": "2026-03-26/logs.jsonl"}]},
        ]
        mock_client.get_object.side_effect = [
            {"Body": BytesIO(_jsonl(*records_day1))},
            {"Body": BytesIO(_jsonl(*records_day2))},
        ]

        with patch(
            "src.core.orchestration.flows.monitoring_flow.boto3.client",
            return_value=mock_client,
        ):
            df = fetch_prediction_logs.fn(
                s3_endpoint="http://minio:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                lookback_days=2,
            )

        assert len(df) == 2

    def test_skips_non_jsonl_files(self) -> None:
        """Non-.jsonl files in the listing are skipped."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "2026-03-27/README.txt"},
                {"Key": "2026-03-27/logs.jsonl"},
            ]
        }
        record = {"predicted_class": "cat", "confidence": 0.9}
        mock_client.get_object.return_value = {"Body": BytesIO(_jsonl(record))}

        with patch(
            "src.core.orchestration.flows.monitoring_flow.boto3.client",
            return_value=mock_client,
        ):
            df = fetch_prediction_logs.fn(
                s3_endpoint="http://minio:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                lookback_days=1,
            )

        # Only one get_object call (for the .jsonl file)
        mock_client.get_object.assert_called_once()
        assert len(df) == 1


class TestFetchReferenceData:
    """Tests for fetch_reference_data task."""

    def test_returns_dataframe_from_s3(self) -> None:
        """Fetches a single JSONL file and returns a DataFrame."""
        records = [
            {"predicted_class": "cat", "confidence": 0.95},
            {"predicted_class": "dog", "confidence": 0.85},
            {"predicted_class": "bird", "confidence": 0.75},
        ]

        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": BytesIO(_jsonl(*records))}

        with patch(
            "src.core.orchestration.flows.monitoring_flow.boto3.client",
            return_value=mock_client,
        ):
            df = fetch_reference_data.fn(
                s3_endpoint="http://minio:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                reference_path="reference/baseline.jsonl",
            )

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "predicted_class" in df.columns
        mock_client.get_object.assert_called_once_with(Bucket="prediction-logs", Key="reference/baseline.jsonl")

    def test_returns_empty_dataframe_for_empty_file(self) -> None:
        """Returns an empty DataFrame when the reference file is empty."""
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": BytesIO(b"")}

        with patch(
            "src.core.orchestration.flows.monitoring_flow.boto3.client",
            return_value=mock_client,
        ):
            df = fetch_reference_data.fn(
                s3_endpoint="http://minio:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                reference_path="reference/baseline.jsonl",
            )

        assert isinstance(df, pd.DataFrame)
        assert df.empty


class TestRunDriftDetection:
    """Tests for run_drift_detection task."""

    def _make_df(self) -> pd.DataFrame:
        """Return a minimal DataFrame for drift testing."""
        return pd.DataFrame(
            {
                "predicted_class": ["cat", "dog", "cat"],
                "confidence": [0.9, 0.8, 0.7],
            }
        )

    def test_calls_detect_drift_and_push_metrics(self) -> None:
        """Both detect_drift and push_drift_metrics are called once."""
        mock_result = {
            "drift_detected": False,
            "drift_score": 0.0,
            "column_drifts": {},
        }

        with (
            patch(
                "src.core.orchestration.flows.monitoring_flow.detect_drift",
                return_value=mock_result,
            ) as mock_detect,
            patch("src.core.orchestration.flows.monitoring_flow.push_drift_metrics") as mock_push,
            patch("src.core.orchestration.flows.monitoring_flow.create_markdown_artifact"),
        ):
            result = run_drift_detection.fn(
                reference=self._make_df(),
                current=self._make_df(),
                pushgateway_url="http://pushgateway:9091",
            )

        mock_detect.assert_called_once()
        mock_push.assert_called_once_with(
            pushgateway_url="http://pushgateway:9091",
            drift_detected=False,
            drift_score=0.0,
            column_drifts={},
        )
        assert result == mock_result

    def test_returns_drift_result_dict(self) -> None:
        """The task returns the dict from detect_drift unchanged."""
        mock_result: dict[str, Any] = {
            "drift_detected": True,
            "drift_score": 0.5,
            "column_drifts": {"confidence": 0.03},
        }

        with (
            patch(
                "src.core.orchestration.flows.monitoring_flow.detect_drift",
                return_value=mock_result,
            ),
            patch("src.core.orchestration.flows.monitoring_flow.push_drift_metrics"),
            patch("src.core.orchestration.flows.monitoring_flow.create_markdown_artifact"),
        ):
            result = run_drift_detection.fn(
                reference=self._make_df(),
                current=self._make_df(),
                pushgateway_url="http://pushgateway:9091",
            )

        assert result["drift_detected"] is True
        assert result["drift_score"] == 0.5
        assert result["column_drifts"] == {"confidence": 0.03}


class TestUploadDriftReport:
    """Tests for upload_drift_report task."""

    def _make_df(self) -> pd.DataFrame:
        """Return a minimal DataFrame for report testing."""
        return pd.DataFrame(
            {
                "predicted_class": ["cat", "dog"],
                "confidence": [0.9, 0.8],
            }
        )

    def test_saves_html_and_uploads_to_s3(self) -> None:
        """save_drift_report_html is called and upload_file sends to S3."""
        mock_client = MagicMock()

        with (
            patch(
                "src.core.orchestration.flows.monitoring_flow.boto3.client",
                return_value=mock_client,
            ),
            patch("src.core.orchestration.flows.monitoring_flow.save_drift_report_html") as mock_save,
        ):
            upload_drift_report.fn(
                reference=self._make_df(),
                current=self._make_df(),
                s3_endpoint="http://minio:9000",
                bucket="drift-reports",
                access_key="minioadmin",
                secret_key="minioadmin123",
            )

        mock_save.assert_called_once()
        mock_client.upload_file.assert_called_once()
        # Verify upload target bucket and key format
        upload_call_args = mock_client.upload_file.call_args
        assert upload_call_args.args[1] == "drift-reports"
        assert upload_call_args.args[2].endswith("/drift-report.html")

    def test_returns_s3_key_string(self) -> None:
        """The returned S3 key is a non-empty string ending in drift-report.html."""
        mock_client = MagicMock()

        with (
            patch(
                "src.core.orchestration.flows.monitoring_flow.boto3.client",
                return_value=mock_client,
            ),
            patch("src.core.orchestration.flows.monitoring_flow.save_drift_report_html"),
        ):
            s3_key = upload_drift_report.fn(
                reference=self._make_df(),
                current=self._make_df(),
                s3_endpoint="http://minio:9000",
                bucket="drift-reports",
                access_key="minioadmin",
                secret_key="minioadmin123",
            )

        assert isinstance(s3_key, str)
        assert s3_key.endswith("/drift-report.html")


class TestRunDriftQualityGate:
    """Tests for run_drift_quality_gate task."""

    @staticmethod
    def _gate_result(passed: bool = True) -> dict[str, object]:
        """Create a mock check_drift_threshold return value."""
        return {
            "passed": passed,
            "drift_score": 0.1 if passed else 0.5,
            "drift_detected": not passed,
            "column_drifts": {"confidence": 0.03},
            "threshold": 0.3,
        }

    def test_returns_result_when_passed(self) -> None:
        """Returns result dict when drift is below threshold."""
        from src.core.orchestration.flows.monitoring_flow import run_drift_quality_gate

        with (
            patch(
                "src.core.orchestration.flows.monitoring_flow.check_drift_threshold",
                return_value=self._gate_result(passed=True),
            ),
            patch("src.core.orchestration.flows.monitoring_flow.create_markdown_artifact"),
        ):
            result = run_drift_quality_gate.fn(
                reference=pd.DataFrame({"a": [1]}),
                current=pd.DataFrame({"a": [1]}),
            )

        assert result["passed"] is True
        assert result["drift_score"] == 0.1

    def test_raises_runtime_error_when_failed(self) -> None:
        """Raises RuntimeError when drift exceeds threshold."""
        import pytest

        from src.core.orchestration.flows.monitoring_flow import run_drift_quality_gate

        with (
            patch(
                "src.core.orchestration.flows.monitoring_flow.check_drift_threshold",
                return_value=self._gate_result(passed=False),
            ),
            patch("src.core.orchestration.flows.monitoring_flow.create_markdown_artifact"),
            pytest.raises(RuntimeError, match="Drift quality gate failed"),
        ):
            run_drift_quality_gate.fn(
                reference=pd.DataFrame({"a": [1]}),
                current=pd.DataFrame({"a": [1]}),
            )

    def test_creates_markdown_artifact(self) -> None:
        """Creates a Prefect markdown artifact with drift quality gate results."""
        from src.core.orchestration.flows.monitoring_flow import run_drift_quality_gate

        with (
            patch(
                "src.core.orchestration.flows.monitoring_flow.check_drift_threshold",
                return_value=self._gate_result(passed=True),
            ),
            patch("src.core.orchestration.flows.monitoring_flow.create_markdown_artifact") as mock_artifact,
        ):
            run_drift_quality_gate.fn(
                reference=pd.DataFrame({"a": [1]}),
                current=pd.DataFrame({"a": [1]}),
            )

        mock_artifact.assert_called_once()
        call_kwargs = mock_artifact.call_args[1]
        assert call_kwargs["key"] == "drift-quality-gate"
        assert "PASSED" in call_kwargs["markdown"]


class TestMonitoringPipelineFailOnDrift:
    """Tests for fail_on_drift parameter in monitoring_pipeline."""

    @staticmethod
    def _setup_pipeline_mocks() -> dict[str, Any]:
        """Create mocks for monitoring_pipeline dependencies."""
        current_df = pd.DataFrame({"predicted_class": [1, 2], "confidence": [0.9, 0.8]})
        reference_df = pd.DataFrame({"predicted_class": [1, 2], "confidence": [0.9, 0.8]})
        drift_result: dict[str, Any] = {
            "drift_detected": True,
            "drift_score": 0.5,
            "column_drifts": {"confidence": 0.03},
        }
        return {
            "current_df": current_df,
            "reference_df": reference_df,
            "drift_result": drift_result,
        }

    def _pipeline_patches(self, mocks: dict[str, Any]) -> dict[str, Any]:
        """Return common patches for monitoring_pipeline tests."""
        mock_cfg = MagicMock()
        mock_cfg.s3_endpoint = "http://minio:9000"
        mock_cfg.s3_access_key = "key"
        mock_cfg.s3_secret_key = "secret"
        mock_cfg.prediction_logs_bucket = "prediction-logs"
        mock_cfg.drift_reports_bucket = "drift-reports"
        mock_cfg.reference_path = "reference/baseline.jsonl"
        mock_cfg.lookback_days = 1
        mock_cfg.pushgateway_url = "http://pushgateway:9091"
        return {
            "config": patch("src.core.orchestration.flows.monitoring_flow.DriftConfig", return_value=mock_cfg),
            "fetch_logs": patch(
                "src.core.orchestration.flows.monitoring_flow.fetch_prediction_logs",
                return_value=mocks["current_df"],
            ),
            "fetch_ref": patch(
                "src.core.orchestration.flows.monitoring_flow.fetch_reference_data",
                return_value=mocks["reference_df"],
            ),
            "drift_detect": patch(
                "src.core.orchestration.flows.monitoring_flow.run_drift_detection",
                return_value=mocks["drift_result"],
            ),
            "quality_gate": patch(
                "src.core.orchestration.flows.monitoring_flow.run_drift_quality_gate",
                side_effect=RuntimeError("Drift quality gate failed"),
            ),
        }

    def test_fail_on_drift_true_raises(self) -> None:
        """Pipeline raises RuntimeError when fail_on_drift=True and drift exceeds threshold."""
        import pytest

        from src.core.orchestration.flows.monitoring_flow import monitoring_pipeline

        mocks = self._setup_pipeline_mocks()
        patches = self._pipeline_patches(mocks)

        with (
            patches["config"],
            patches["fetch_logs"],
            patches["fetch_ref"],
            patches["drift_detect"],
            patches["quality_gate"],
            patch("src.core.orchestration.flows.monitoring_flow.upload_drift_report"),
            pytest.raises(RuntimeError, match="Drift quality gate failed"),
        ):
            monitoring_pipeline.fn(fail_on_drift=True)

    def test_fail_on_drift_false_continues(self) -> None:
        """Pipeline continues to report upload when fail_on_drift=False (default)."""
        from src.core.orchestration.flows.monitoring_flow import monitoring_pipeline

        mocks = self._setup_pipeline_mocks()
        patches = self._pipeline_patches(mocks)

        with (
            patches["config"],
            patches["fetch_logs"],
            patches["fetch_ref"],
            patches["drift_detect"],
            patches["quality_gate"],
            patch(
                "src.core.orchestration.flows.monitoring_flow.upload_drift_report",
                return_value="2026-03-29/drift-report.html",
            ) as mock_upload,
        ):
            result = monitoring_pipeline.fn(fail_on_drift=False)

        mock_upload.assert_called_once()
        assert result["status"] == "completed"
