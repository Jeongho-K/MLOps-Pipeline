"""Drift detection configuration using Pydantic Settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class DriftConfig(BaseSettings):
    """Configuration for Evidently drift detection.

    Values can be overridden via environment variables with DRIFT_ prefix.
    """

    model_config = {"env_prefix": "DRIFT_"}

    # S3 / MinIO
    s3_endpoint: str = Field(default="http://minio:9000", description="MinIO endpoint URL")
    s3_access_key: str = Field(description="S3 access key (env: DRIFT_S3_ACCESS_KEY)")
    s3_secret_key: str = Field(description="S3 secret key (env: DRIFT_S3_SECRET_KEY)")

    # Buckets
    prediction_logs_bucket: str = Field(default="prediction-logs", description="Bucket for prediction logs")
    drift_reports_bucket: str = Field(default="drift-reports", description="Bucket for drift HTML reports")

    # Reference data
    reference_path: str = Field(default="reference/baseline.jsonl", description="S3 key for reference dataset")

    # Analysis
    lookback_days: int = Field(default=1, ge=1, description="Number of days of logs to analyze")

    # Pushgateway
    pushgateway_url: str = Field(default="http://pushgateway:9091", description="Prometheus Pushgateway URL")
