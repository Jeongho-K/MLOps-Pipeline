"""Image dataset validation using CleanVision.

Detects common image quality issues: blurry, dark/bright, duplicates,
odd sizes, and other artifacts before training.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cleanvision import Imagelab

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Summary of image dataset validation results."""

    total_images: int = 0
    issues_found: int = 0
    issue_types: dict[str, int] = field(default_factory=dict)
    health_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for MLflow logging."""
        return {
            "total_images": self.total_images,
            "issues_found": self.issues_found,
            "health_score": self.health_score,
            **{f"issue_{k}": v for k, v in self.issue_types.items()},
        }


def validate_image_dataset(
    dataset_path: str | Path,
    issue_types: list[str] | None = None,
) -> ValidationReport:
    """Run CleanVision validation on an image dataset.

    Args:
        dataset_path: Path to directory containing images.
        issue_types: Specific issue types to check. None checks all.
            Options: "dark", "light", "odd_aspect_ratio", "odd_size",
            "low_information", "exact_duplicates", "near_duplicates",
            "blurry".

    Returns:
        ValidationReport with summary statistics.
    """
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset path does not exist: {dataset_path}")

    logger.info("Starting CleanVision validation on %s", dataset_path)

    try:
        imagelab = Imagelab(data_path=str(dataset_path))
    except (OSError, ValueError, RuntimeError) as e:
        raise RuntimeError(f"Failed to load images from {dataset_path}: {e}") from e

    if len(imagelab.issues) == 0:
        logger.warning("No images found in %s", dataset_path)
        return ValidationReport()

    try:
        if issue_types:
            imagelab.find_issues(issue_types={t: {} for t in issue_types})
        else:
            imagelab.find_issues()
    except (OSError, ValueError, RuntimeError) as e:
        raise RuntimeError(f"CleanVision analysis failed on {dataset_path}: {e}") from e

    summary = imagelab.issue_summary
    total_images = len(imagelab.issues)

    issue_counts: dict[str, int] = {}
    for issue_type in summary.index:
        count = int(summary.loc[issue_type, "num_images"])
        if count > 0:
            issue_counts[issue_type] = count

    # Count unique images with at least one issue (avoids double-counting)
    any_issue_col = [c for c in imagelab.issues.columns if c.startswith("is_") and c.endswith("_issue")]
    images_with_issues = int(imagelab.issues[any_issue_col].any(axis=1).sum()) if any_issue_col else 0
    health_score = 1.0 - (images_with_issues / max(total_images, 1))

    report = ValidationReport(
        total_images=total_images,
        issues_found=images_with_issues,
        issue_types=issue_counts,
        health_score=max(health_score, 0.0),
    )

    logger.info(
        "Validation complete: %d images, %d issues, health=%.2f",
        report.total_images,
        report.issues_found,
        report.health_score,
    )

    return report


VALID_ISSUE_TYPES = {
    "dark", "light", "odd_aspect_ratio", "odd_size",
    "low_information", "exact_duplicates", "near_duplicates", "blurry",
}


def get_issue_image_paths(
    dataset_path: str | Path,
    issue_type: str,
) -> list[Path]:
    """Get paths of images flagged for a specific issue type.

    Note: This re-runs CleanVision analysis. For large datasets,
    consider caching the Imagelab instance.

    Args:
        dataset_path: Path to directory containing images.
        issue_type: The issue type to filter by.
            See validate_image_dataset for valid issue types.

    Returns:
        List of image paths with the specified issue.
    """
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset path does not exist: {dataset_path}")

    if issue_type not in VALID_ISSUE_TYPES:
        raise ValueError(
            f"Unknown issue type '{issue_type}'. Valid types: {sorted(VALID_ISSUE_TYPES)}"
        )

    imagelab = Imagelab(data_path=str(dataset_path))
    imagelab.find_issues(issue_types={issue_type: {}})

    issue_col = f"is_{issue_type}_issue"
    flagged = imagelab.issues[imagelab.issues[issue_col]]

    return [Path(idx) for idx in flagged.index]
