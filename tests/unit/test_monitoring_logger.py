"""Unit tests for prediction_logger module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.monitoring.prediction_logger import PredictionLog, PredictionLogger


class TestPredictionLog:
    """Tests for PredictionLog dataclass."""

    def _make_log(self) -> PredictionLog:
        return PredictionLog(
            timestamp="2024-01-15T10:00:00+00:00",
            predicted_class=2,
            class_name="cat",
            confidence=0.92,
            probabilities=[0.03, 0.05, 0.92],
        )

    def test_to_dict_returns_all_fields(self) -> None:
        """to_dict() should return a dict with all dataclass fields."""
        log = self._make_log()
        result = log.to_dict()
        assert result == {
            "timestamp": "2024-01-15T10:00:00+00:00",
            "predicted_class": 2,
            "class_name": "cat",
            "confidence": 0.92,
            "probabilities": [0.03, 0.05, 0.92],
        }

    def test_to_dict_with_none_class_name(self) -> None:
        """to_dict() should preserve None class_name."""
        log = PredictionLog(
            timestamp="2024-01-15T10:00:00+00:00",
            predicted_class=0,
            class_name=None,
            confidence=0.5,
            probabilities=[0.5, 0.5],
        )
        assert log.to_dict()["class_name"] is None

    def test_to_json_line_is_valid_json(self) -> None:
        """to_json_line() should produce a valid JSON string."""
        log = self._make_log()
        line = log.to_json_line()
        parsed = json.loads(line)
        assert parsed["predicted_class"] == 2
        assert parsed["class_name"] == "cat"

    def test_to_json_line_has_no_trailing_newline(self) -> None:
        """to_json_line() must not contain a trailing newline."""
        log = self._make_log()
        assert not log.to_json_line().endswith("\n")


class TestPredictionLoggerBuffer:
    """Tests for PredictionLogger buffering behaviour (no real S3 calls)."""

    def _make_logger(self, flush_threshold: int = 50) -> PredictionLogger:
        with patch("src.monitoring.prediction_logger.boto3.client"):
            pl = PredictionLogger(
                s3_endpoint="http://localhost:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                flush_threshold=flush_threshold,
            )
        return pl

    def test_log_adds_to_buffer(self) -> None:
        """log() should append one entry to the internal buffer."""
        pl = self._make_logger()
        pl.log(predicted_class=1, confidence=0.8, probabilities=[0.2, 0.8])
        assert len(pl._buffer) == 1
        assert pl._buffer[0].predicted_class == 1
        assert pl._buffer[0].confidence == 0.8

    def test_log_stores_class_name(self) -> None:
        """log() should store class_name when provided."""
        pl = self._make_logger()
        pl.log(predicted_class=0, confidence=0.9, probabilities=[0.9, 0.1], class_name="dog")
        assert pl._buffer[0].class_name == "dog"

    def test_log_without_class_name_defaults_to_none(self) -> None:
        """log() without class_name should store None."""
        pl = self._make_logger()
        pl.log(predicted_class=0, confidence=0.9, probabilities=[0.9, 0.1])
        assert pl._buffer[0].class_name is None

    def test_multiple_logs_accumulate(self) -> None:
        """Multiple log() calls should accumulate in the buffer."""
        pl = self._make_logger(flush_threshold=10)
        for i in range(5):
            pl.log(predicted_class=i, confidence=0.5, probabilities=[0.5, 0.5])
        assert len(pl._buffer) == 5

    def test_auto_flush_at_threshold(self) -> None:
        """Buffer should be cleared after reaching flush_threshold."""
        pl = self._make_logger(flush_threshold=3)
        pl._s3_client.put_object = MagicMock()

        for i in range(3):
            pl.log(predicted_class=i, confidence=0.5, probabilities=[0.5, 0.5])

        # After reaching threshold the buffer is flushed
        assert len(pl._buffer) == 0
        pl._s3_client.put_object.assert_called_once()

    def test_auto_flush_uploads_all_records(self) -> None:
        """Auto-flush should upload exactly the records that were buffered."""
        pl = self._make_logger(flush_threshold=2)
        pl._s3_client.put_object = MagicMock()

        pl.log(predicted_class=0, confidence=0.6, probabilities=[0.6, 0.4])
        pl.log(predicted_class=1, confidence=0.9, probabilities=[0.1, 0.9])

        call_kwargs = pl._s3_client.put_object.call_args[1]
        body_text = call_kwargs["Body"].decode("utf-8")
        lines = body_text.splitlines()
        assert len(lines) == 2


class TestPredictionLoggerFlush:
    """Tests for explicit flush() behaviour."""

    def _make_logger_with_mock_s3(self, flush_threshold: int = 50) -> PredictionLogger:
        with patch("src.monitoring.prediction_logger.boto3.client"):
            pl = PredictionLogger(
                s3_endpoint="http://localhost:9000",
                bucket="prediction-logs",
                access_key="minioadmin",
                secret_key="minioadmin123",
                flush_threshold=flush_threshold,
            )
        pl._s3_client = MagicMock()
        return pl

    def test_flush_empty_buffer_is_noop(self) -> None:
        """flush() on an empty buffer should not call S3 at all."""
        pl = self._make_logger_with_mock_s3()
        pl.flush()
        pl._s3_client.put_object.assert_not_called()

    def test_flush_uploads_jsonl(self) -> None:
        """flush() should upload a JSONL file to the correct bucket."""
        pl = self._make_logger_with_mock_s3()
        pl.log(predicted_class=1, confidence=0.75, probabilities=[0.25, 0.75])
        pl.flush()

        pl._s3_client.put_object.assert_called_once()
        call_kwargs = pl._s3_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "prediction-logs"
        assert call_kwargs["Key"].endswith(".jsonl")
        body_text = call_kwargs["Body"].decode("utf-8")
        parsed = json.loads(body_text)
        assert parsed["predicted_class"] == 1

    def test_flush_key_uses_date_prefix(self) -> None:
        """flush() S3 key should start with a YYYY-MM-DD date prefix."""
        pl = self._make_logger_with_mock_s3()
        pl.log(predicted_class=0, confidence=0.5, probabilities=[0.5, 0.5])
        pl.flush()

        call_kwargs = pl._s3_client.put_object.call_args[1]
        key: str = call_kwargs["Key"]
        # Key format: YYYY-MM-DD/<uuid>.jsonl
        date_part = key.split("/")[0]
        assert len(date_part) == 10
        assert date_part[4] == "-" and date_part[7] == "-"

    def test_flush_clears_buffer(self) -> None:
        """After a successful flush the buffer should be empty."""
        pl = self._make_logger_with_mock_s3()
        pl.log(predicted_class=0, confidence=0.5, probabilities=[0.5, 0.5])
        pl.flush()
        assert len(pl._buffer) == 0

    def test_flush_requeues_on_s3_failure(self) -> None:
        """On upload failure records should be re-added to the buffer for retry."""
        from botocore.exceptions import ClientError

        pl = self._make_logger_with_mock_s3()
        pl._s3_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "bucket not found"}},
            "PutObject",
        )

        pl.log(predicted_class=0, confidence=0.5, probabilities=[0.5, 0.5])
        pl.flush()

        # Record should be back in the buffer
        assert len(pl._buffer) == 1

    def test_flush_uploads_multiple_records_as_multiline_jsonl(self) -> None:
        """flush() should separate records by newlines when there are multiple."""
        pl = self._make_logger_with_mock_s3()
        for i in range(3):
            pl.log(predicted_class=i, confidence=0.5, probabilities=[0.5, 0.5])
        pl.flush()

        call_kwargs = pl._s3_client.put_object.call_args[1]
        body_text = call_kwargs["Body"].decode("utf-8")
        lines = body_text.splitlines()
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # each line must be valid JSON
