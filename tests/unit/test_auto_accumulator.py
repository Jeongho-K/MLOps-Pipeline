"""Unit tests for the AutoAccumulator and AccumulatedSample."""

from __future__ import annotations

import json
import logging
import threading
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from src.core.active_learning.accumulator.auto_accumulator import AutoAccumulator
from src.core.active_learning.accumulator.models import AccumulatedSample


def _make_sample(
    predicted_class=0,
    class_name="cat",
    confidence=0.95,
    probabilities=None,
    model_version="1",
    image_ref="",
):
    return AccumulatedSample(
        timestamp="2026-03-29T12:00:00+00:00",
        predicted_class=predicted_class,
        class_name=class_name,
        confidence=confidence,
        probabilities=probabilities or [0.95, 0.05],
        model_version=model_version,
        image_ref=image_ref,
    )


class TestAccumulatedSample:
    def test_to_dict(self) -> None:
        sample = _make_sample()
        d = sample.to_dict()
        assert d["timestamp"] == "2026-03-29T12:00:00+00:00"
        assert d["predicted_class"] == 0
        assert d["class_name"] == "cat"
        assert d["confidence"] == 0.95
        assert d["probabilities"] == [0.95, 0.05]
        assert d["model_version"] == "1"
        assert d["image_ref"] == ""

    def test_to_json_line(self) -> None:
        sample = _make_sample()
        line = sample.to_json_line()
        parsed = json.loads(line)
        assert parsed == sample.to_dict()
        assert "\n" not in line


class TestAutoAccumulator:
    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_add_increases_buffer(self, mock_boto_client):
        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret", flush_threshold=100)
        assert acc.buffer_size == 0
        acc.add(_make_sample())
        assert acc.buffer_size == 1
        acc.add(_make_sample())
        assert acc.buffer_size == 2

    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_auto_flush_at_threshold(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret", flush_threshold=3)
        acc.add(_make_sample(predicted_class=0))
        acc.add(_make_sample(predicted_class=1))
        assert acc.buffer_size == 2

        acc.add(_make_sample(predicted_class=2))
        # Buffer should be flushed (auto-flush at threshold=3)
        mock_s3.put_object.assert_called_once()
        assert acc.buffer_size == 0

    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_flush_uploads_to_s3(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret")
        acc.add(_make_sample())
        acc.add(_make_sample())
        count = acc.flush()

        assert count == 2
        assert acc.buffer_size == 0
        mock_s3.put_object.assert_called_once()

        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "bucket"
        assert call_kwargs["Key"].startswith("accumulated/")
        assert call_kwargs["Key"].endswith(".jsonl")
        assert call_kwargs["ContentType"] == "application/x-ndjson"

    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_flush_empty_buffer_returns_zero(self, mock_boto_client):
        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret")
        assert acc.flush() == 0

    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_flush_requeues_on_s3_error(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = ClientError(
            error_response={"Error": {"Code": "500", "Message": "Internal"}},
            operation_name="PutObject",
        )
        mock_boto_client.return_value = mock_s3

        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret")
        acc.add(_make_sample())
        acc.add(_make_sample())
        count = acc.flush()

        assert count == 0
        assert acc.buffer_size == 2

    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_class_distribution_warning(self, mock_boto_client, caplog):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret")
        # All 5 samples have the same class → 100% > 80% threshold
        for _ in range(5):
            acc.add(_make_sample(predicted_class=0))

        with caplog.at_level(logging.WARNING, logger="src.core.active_learning.accumulator.auto_accumulator"):
            acc.flush()

        assert any("Class imbalance" in msg for msg in caplog.messages)

    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_no_class_distribution_warning_when_balanced(self, mock_boto_client, caplog):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret")
        # 5 different classes → 20% each, well below 80%
        for i in range(5):
            acc.add(_make_sample(predicted_class=i))

        with caplog.at_level(logging.WARNING, logger="src.core.active_learning.accumulator.auto_accumulator"):
            acc.flush()

        assert not any("Class imbalance" in msg for msg in caplog.messages)

    @patch("src.core.active_learning.accumulator.auto_accumulator.boto3.client")
    def test_thread_safety(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        acc = AutoAccumulator("http://minio:9000", "bucket", "accumulated/", "key", "secret", flush_threshold=10_000)
        num_threads = 10
        samples_per_thread = 100

        def add_samples():
            for _ in range(samples_per_thread):
                acc.add(_make_sample())

        threads = [threading.Thread(target=add_samples) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert acc.buffer_size == num_threads * samples_per_thread
