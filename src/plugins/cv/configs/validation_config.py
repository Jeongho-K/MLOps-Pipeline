"""Validation configuration using Pydantic Settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class ValidationConfig(BaseSettings):
    """Configuration for data validation.

    Values can be overridden via environment variables with VALIDATION_ prefix.
    """

    model_config = {"env_prefix": "VALIDATION_"}

    issue_types: list[str] | None = Field(
        default=None,
        description="CleanVision issue types to check. None checks all. "
        "Options: dark, light, odd_aspect_ratio, odd_size, low_information, "
        "exact_duplicates, near_duplicates, blurry",
    )
    min_health_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum data health score to proceed with training",
    )
