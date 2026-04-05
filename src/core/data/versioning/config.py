"""DVC versioning configuration using Pydantic Settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class DVCConfig(BaseSettings):
    """Configuration for DVC data versioning.

    Values can be overridden via environment variables with DVC_ prefix.
    """

    model_config = {"env_prefix": "DVC_"}

    remote_name: str = Field(
        default="minio-remote",
        description="Name of the DVC remote to use for push/pull operations",
    )
    repo_root: str = Field(
        default=".",
        description="Root directory of the DVC repository",
    )
    push_to_remote: bool = Field(
        default=True,
        description="Whether to push versioned data to the remote after add",
    )
    verify_checksum: bool = Field(
        default=True,
        description="Whether to verify data integrity after pull operations",
    )
