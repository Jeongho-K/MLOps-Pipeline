"""Configuration for the Active Learning Engine.

All settings are loaded from environment variables with the ``AL_`` prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class ActiveLearningConfig(BaseSettings):
    """Active Learning configuration loaded from environment variables.

    Attributes:
        auto_accumulate_threshold: Minimum confidence for pseudo-labeling.
        uncertainty_threshold: Minimum uncertainty to route to human review.
        accumulation_buffer_size: Buffer size before auto-flush to S3.
        max_pseudo_label_ratio: Maximum pseudo-label ratio in training data.
        accumulation_bucket: S3 bucket for accumulated pseudo-labels.
        accumulation_prefix: S3 key prefix for accumulated data.
        s3_endpoint: S3/MinIO endpoint URL.
        label_studio_url: Label Studio API base URL.
        label_studio_api_key: Label Studio API token.
        label_studio_project_id: Default Label Studio project ID.
    """

    model_config = {"env_prefix": "AL_"}

    # Confidence routing
    auto_accumulate_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for auto-accumulation as pseudo-label.",
    )
    uncertainty_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum uncertainty score to route to human review.",
    )

    # Auto-accumulator
    accumulation_buffer_size: int = Field(
        default=500,
        ge=1,
        description="Number of samples that triggers auto-flush to S3.",
    )
    max_pseudo_label_ratio: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Maximum pseudo-label ratio in total training data.",
    )
    accumulation_bucket: str = Field(
        default="active-learning",
        description="S3 bucket for accumulated pseudo-labels.",
    )
    accumulation_prefix: str = Field(
        default="accumulated/",
        description="S3 key prefix for accumulated data.",
    )

    # S3 / MinIO
    s3_endpoint: str = Field(
        default="http://minio:9000",
        description="S3-compatible endpoint URL.",
    )

    # Label Studio
    label_studio_url: str = Field(
        default="http://label-studio:8080",
        description="Label Studio API base URL.",
    )
    label_studio_api_key: str = Field(
        default="",
        description="Label Studio API token.",
    )
    label_studio_project_id: int = Field(
        default=1,
        ge=1,
        description="Default Label Studio project ID.",
    )
