"""Serving configuration using Pydantic Settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class ServingConfig(BaseSettings):
    """Configuration for the inference API server.

    Values can be overridden via environment variables with SERVING_ prefix.
    """

    model_config = {"env_prefix": "SERVING_"}

    # Model loading
    model_name: str = Field(default="cv-classifier", description="MLflow registered model name")
    model_version: str = Field(default="latest", description="Model version to load")
    mlflow_tracking_uri: str = Field(default="http://mlflow:5000", description="MLflow server URI")

    # Inference
    image_size: int = Field(default=224, ge=1, description="Input image size for preprocessing")
    device: Literal["auto", "cpu", "cuda", "mps"] = Field(default="auto", description="Inference device")

    # Class names (optional, comma-separated)
    class_names: str | None = Field(default=None, description="Comma-separated class names (e.g. 'cat,dog,bird')")

    # Server
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server bind port")

    # Prediction logging (S3 credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars)
    s3_endpoint: str = Field(default="http://minio:9000", description="S3 endpoint for prediction logs")
    prediction_logs_bucket: str = Field(default="prediction-logs", description="S3 bucket for prediction logs")

    def get_class_names_list(self) -> list[str] | None:
        """Parse comma-separated class names into a list."""
        if self.class_names is None:
            return None
        return [name.strip() for name in self.class_names.split(",") if name.strip()]
