"""Prefect tasks for data pipeline operations."""

from __future__ import annotations

import logging
from pathlib import Path

from prefect import task

logger = logging.getLogger(__name__)


@task(name="prepare-dataset", retries=1, retry_delay_seconds=30)
def prepare_dataset(data_dir: str) -> Path:
    """Verify dataset exists and return its path.

    Args:
        data_dir: Path to the dataset directory.

    Returns:
        Resolved dataset path.

    Raises:
        FileNotFoundError: If dataset directory or train/val splits are missing.
    """
    path = Path(data_dir)
    if not path.exists():
        raise FileNotFoundError(f"Dataset directory not found: {path}")

    train_dir = path / "train"
    val_dir = path / "val"
    if not train_dir.exists() or not val_dir.exists():
        raise FileNotFoundError(f"Dataset must contain 'train/' and 'val/' subdirectories: {path}")

    train_count = sum(1 for p in train_dir.rglob("*") if p.is_file())
    val_count = sum(1 for p in val_dir.rglob("*") if p.is_file())
    logger.info("Dataset ready: %d train, %d val images at %s", train_count, val_count, path)

    return path


@task(name="validate-images", retries=1, retry_delay_seconds=10)
def validate_images(data_dir: Path) -> dict[str, float]:
    """Run CleanVision image quality validation.

    Args:
        data_dir: Path to dataset directory with train/ subdirectory.

    Returns:
        Validation metrics dict for MLflow logging.
    """
    from src.data.validation import validate_image_dataset

    train_dir = data_dir / "train"
    report = validate_image_dataset(train_dir)
    logger.info(
        "Image validation: %d images, %d issues, health=%.2f",
        report.total_images, report.issues_found, report.health_score,
    )
    return report.to_dict()
