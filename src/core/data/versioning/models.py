"""Data models for DVC versioning operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class VersioningResult:
    """Result of a DVC versioning operation for one active learning round."""

    data_dir: str
    data_hash: str = ""
    dvc_added: bool = False
    dvc_pushed: bool = False
    checksum_verified: bool = False
    round_num: int = 0
    timestamp: str = ""

    def __post_init__(self) -> None:
        """Set timestamp if not provided."""
        if not self.timestamp:
            self.timestamp = datetime.now(tz=UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for MLflow logging and Prefect artifacts."""
        return {
            "data_dir": self.data_dir,
            "data_hash": self.data_hash,
            "dvc_added": self.dvc_added,
            "dvc_pushed": self.dvc_pushed,
            "checksum_verified": self.checksum_verified,
            "round_num": self.round_num,
            "timestamp": self.timestamp,
        }


@dataclass
class RoundSnapshot:
    """Metadata for a single active learning round's data state.

    Used for intermediate data versioning within a round.
    The previous_hash field chains snapshots together for data evolution tracking.
    """

    round_num: int
    data_hash: str
    sample_count: int
    stage: str = ""
    images_removed: int = 0
    labels_removed: int = 0
    cleaning_stats: dict[str, Any] = field(default_factory=dict)
    previous_hash: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        """Set timestamp if not provided."""
        if not self.timestamp:
            self.timestamp = datetime.now(tz=UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging and artifacts."""
        return {
            "round_num": self.round_num,
            "data_hash": self.data_hash,
            "sample_count": self.sample_count,
            "stage": self.stage,
            "images_removed": self.images_removed,
            "labels_removed": self.labels_removed,
            "cleaning_stats": self.cleaning_stats,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
        }
