"""Prediction logger that buffers and uploads prediction logs to MinIO as JSONL."""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import uuid
from datetime import UTC, datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class PredictionLog:
    """A single prediction log entry.

    Attributes:
        timestamp: ISO-8601 UTC timestamp of the prediction.
        predicted_class: Predicted class index.
        class_name: Human-readable class name, or None if not available.
        confidence: Confidence score of the predicted class (0-1).
        probabilities: Full probability distribution across all classes.
        model_version: MLflow model version that generated this prediction.
        mlflow_run_id: MLflow run ID of the training run that produced the model.
    """

    timestamp: str
    predicted_class: int
    class_name: str | None
    confidence: float
    probabilities: list[float]
    model_version: str = ""
    mlflow_run_id: str = ""
    uncertainty_score: float | None = None
    routing_decision: str | None = None

    def to_dict(self) -> dict:
        """Return the log entry as a plain dictionary.

        Returns:
            Dictionary representation of this log entry.
        """
        return dataclasses.asdict(self)

    def to_json_line(self) -> str:
        """Return the log entry as a single JSON line without a trailing newline.

        Returns:
            JSON-serialized string for this log entry.
        """
        return json.dumps(self.to_dict())


class PredictionLogger:
    """Thread-safe logger that batches predictions and uploads them to MinIO as JSONL.

    Predictions are buffered in memory and flushed to S3-compatible storage once
    the buffer reaches ``flush_threshold`` entries or when ``flush()`` is called
    explicitly (e.g. on application shutdown).

    Args:
        s3_endpoint: S3/MinIO endpoint URL (e.g. ``http://minio:9000``).
        bucket: Target bucket name for uploaded JSONL files.
        access_key: S3 access key ID.
        secret_key: S3 secret access key.
        flush_threshold: Number of buffered records that triggers an automatic flush.
    """

    def __init__(
        self,
        s3_endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        flush_threshold: int = 50,
    ) -> None:
        self._s3_endpoint = s3_endpoint
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._flush_threshold = flush_threshold

        self._buffer: list[PredictionLog] = []
        self._lock = threading.Lock()

        self._s3_client = boto3.client(
            "s3",
            endpoint_url=s3_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def log(
        self,
        predicted_class: int,
        confidence: float,
        probabilities: list[float],
        class_name: str | None = None,
        model_version: str = "",
        mlflow_run_id: str = "",
        uncertainty_score: float | None = None,
        routing_decision: str | None = None,
    ) -> None:
        """Append a prediction to the buffer, flushing automatically at threshold.

        Args:
            predicted_class: Predicted class index.
            confidence: Confidence score of the predicted class (0-1).
            probabilities: Full probability distribution across all classes.
            class_name: Human-readable class name, or None if not available.
            model_version: MLflow model version that generated this prediction.
            mlflow_run_id: MLflow run ID of the training run that produced the model.
            uncertainty_score: Uncertainty score from the AL estimator, if available.
            routing_decision: AL routing decision (auto_accumulate/human_review/discard).
        """
        timestamp = datetime.now(tz=UTC).isoformat()
        entry = PredictionLog(
            timestamp=timestamp,
            predicted_class=predicted_class,
            class_name=class_name,
            confidence=confidence,
            probabilities=probabilities,
            model_version=model_version,
            mlflow_run_id=mlflow_run_id,
            uncertainty_score=uncertainty_score,
            routing_decision=routing_decision,
        )

        with self._lock:
            self._buffer.append(entry)
            should_flush = len(self._buffer) >= self._flush_threshold

        if should_flush:
            self.flush()

    def flush(self) -> None:
        """Upload all buffered records to MinIO as a single JSONL file.

        The key is ``{YYYY-MM-DD}/{uuid_hex}.jsonl``.  On upload failure the
        records are re-added to the buffer so they can be retried later.

        If the buffer is empty this method is a no-op.
        """
        with self._lock:
            if not self._buffer:
                return
            records = self._buffer[:]
            self._buffer.clear()

        date_prefix = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        key = f"{date_prefix}/{uuid.uuid4().hex}.jsonl"
        body = "\n".join(record.to_json_line() for record in records)

        try:
            self._s3_client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            logger.info(
                "Flushed %d prediction log(s) to s3://%s/%s",
                len(records),
                self._bucket,
                key,
            )
        except (BotoCoreError, ClientError):
            logger.exception(
                "Failed to upload prediction logs to s3://%s/%s — re-queuing %d record(s)",
                self._bucket,
                key,
                len(records),
            )
            with self._lock:
                self._buffer = records + self._buffer
