"""Auto-accumulator that buffers high-confidence predictions as pseudo-labels and flushes to S3 as JSONL."""

from __future__ import annotations

import logging
import threading
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from src.core.active_learning.accumulator.models import AccumulatedSample

logger = logging.getLogger(__name__)


class AutoAccumulator:
    """Thread-safe accumulator that batches pseudo-labeled samples and uploads them to S3 as JSONL.

    High-confidence predictions are buffered in memory and flushed to S3-compatible
    storage once the buffer reaches ``flush_threshold`` entries or when ``flush()``
    is called explicitly (e.g. on application shutdown).

    Args:
        s3_endpoint: S3/MinIO endpoint URL (e.g. ``http://minio:9000``).
        bucket: Target bucket name for uploaded JSONL files.
        prefix: Key prefix for uploaded files (e.g. ``"accumulated/"``).
        access_key: S3 access key ID.
        secret_key: S3 secret access key.
        flush_threshold: Number of buffered records that triggers an automatic flush.
    """

    def __init__(
        self,
        s3_endpoint: str,
        bucket: str,
        prefix: str,
        access_key: str,
        secret_key: str,
        flush_threshold: int = 500,
    ) -> None:
        self._s3_endpoint = s3_endpoint
        self._bucket = bucket
        self._prefix = prefix
        self._access_key = access_key
        self._secret_key = secret_key
        self._flush_threshold = flush_threshold

        self._buffer: list[AccumulatedSample] = []
        self._lock = threading.Lock()

        self._s3_client = boto3.client(
            "s3",
            endpoint_url=s3_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    @property
    def buffer_size(self) -> int:
        """Return the current number of buffered samples."""
        with self._lock:
            return len(self._buffer)

    def add(self, sample: AccumulatedSample) -> None:
        """Append a pseudo-labeled sample to the buffer, flushing automatically at threshold.

        Args:
            sample: The accumulated sample to add.
        """
        with self._lock:
            self._buffer.append(sample)
            should_flush = len(self._buffer) >= self._flush_threshold

        if should_flush:
            self.flush()

    def flush(self) -> int:
        """Upload all buffered records to S3 as a single JSONL file.

        The key is ``{prefix}{YYYY-MM-DD}/{uuid_hex}.jsonl``.  On upload failure the
        records are re-added to the buffer so they can be retried later.

        On successful flush, a warning is logged if any single class accounts for
        more than 80% of the batch (class imbalance).

        Returns:
            Number of records flushed, or 0 if the buffer was empty or upload failed.
        """
        with self._lock:
            if not self._buffer:
                return 0
            records = self._buffer[:]
            self._buffer.clear()

        date_prefix = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        key = f"{self._prefix}{date_prefix}/{uuid.uuid4().hex}.jsonl"
        body = "\n".join(record.to_json_line() for record in records)

        try:
            self._s3_client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            logger.info(
                "Flushed %d accumulated sample(s) to s3://%s/%s",
                len(records),
                self._bucket,
                key,
            )
        except (BotoCoreError, ClientError):
            logger.exception(
                "Failed to upload accumulated samples to s3://%s/%s — re-queuing %d record(s)",
                self._bucket,
                key,
                len(records),
            )
            with self._lock:
                self._buffer = records + self._buffer
            return 0

        # Class distribution check: warn if a single class dominates the batch.
        class_counts = Counter(record.predicted_class for record in records)
        total = len(records)
        for cls, count in class_counts.items():
            if count / total > 0.8:
                logger.warning(
                    "Class imbalance detected in accumulated batch: class %d accounts for %.1f%% (%d/%d)",
                    cls,
                    count / total * 100,
                    count,
                    total,
                )
                break

        return len(records)
