"""Prefect tasks for data pipeline operations."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch
from prefect import task
from prefect.artifacts import create_markdown_artifact
from prefect.cache_policies import INPUTS
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

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


@task(
    name="validate-images",
    retries=1,
    retry_delay_seconds=10,
    cache_policy=INPUTS,
    cache_expiration=timedelta(hours=1),
)
def validate_images(data_dir: str) -> dict[str, Any]:
    """Run CleanVision image quality validation.

    Args:
        data_dir: Path to dataset directory with train/ subdirectory.

    Returns:
        Dict with keys 'total_images', 'issues_found', 'health_score' (0.0-1.0),
        and 'issue_{type}' counts.
    """
    from src.plugins.cv.configs.validation_config import ValidationConfig
    from src.plugins.cv.validator import validate_image_dataset

    config = ValidationConfig()
    train_dir = Path(data_dir) / "train"
    report = validate_image_dataset(train_dir, issue_types=config.issue_types)
    logger.info(
        "Image validation: %d images, %d issues, health=%.2f",
        report.total_images,
        report.issues_found,
        report.health_score,
    )

    result = report.to_dict()

    # Create Prefect artifact for UI visibility
    issue_rows = ""
    for key, value in result.items():
        if key.startswith("issue_"):
            issue_type = key.replace("issue_", "")
            issue_rows += f"| {issue_type} | {value} |\n"

    markdown = f"""## Image Validation Report
| Metric | Value |
|--------|-------|
| Total Images | {result.get("total_images", "N/A")} |
| Issues Found | {result.get("issues_found", "N/A")} |
| Health Score | {result.get("health_score", 0):.2f} |

### Issue Breakdown
| Issue Type | Count |
|------------|-------|
{issue_rows}"""
    create_markdown_artifact(key="image-validation-report", markdown=markdown)

    return result


@task(name="validate-labels", retries=1, retry_delay_seconds=10)
def validate_labels_task(
    model_uri: str,
    data_dir: str,
    device: str,
    num_classes: int,
    image_size: int = 224,
    mlflow_run_id: str | None = None,
    mlflow_tracking_uri: str | None = None,
) -> dict[str, Any]:
    """Validate labels using trained model predictions (post-hoc).

    Loads the model from MLflow registry, runs inference on the training set
    to get predicted probabilities, then uses CleanLab to detect label issues.

    Args:
        model_uri: MLflow model URI (e.g. "models:/my-model@challenger").
        data_dir: Path to dataset directory with train/ subdirectory.
        device: Device string (cpu/cuda/mps).
        num_classes: Number of output classes.
        image_size: Input image size for transforms.
        mlflow_run_id: If provided, log CleanLab metrics to this MLflow run.
        mlflow_tracking_uri: MLflow tracking server URI (required with mlflow_run_id).

    Returns:
        Dict with label quality metrics from LabelReport.to_dict().
    """
    import mlflow.pytorch

    from src.plugins.cv.label_validator import validate_labels
    from src.plugins.cv.transforms import get_eval_transforms

    if mlflow_tracking_uri:
        mlflow.set_tracking_uri(mlflow_tracking_uri)

    model = mlflow.pytorch.load_model(model_uri, map_location="cpu")

    train_dir = Path(data_dir) / "train"
    dataset = ImageFolder(str(train_dir), transform=get_eval_transforms(image_size))
    loader = DataLoader(dataset, batch_size=64, shuffle=False, num_workers=0)

    torch_device = torch.device(device)
    model = model.to(torch_device)
    model.eval()

    all_labels: list[int] = []
    all_probs: list[np.ndarray] = []

    with torch.no_grad():
        for images, targets in loader:
            outputs = model(images.to(torch_device))
            probs = torch.softmax(outputs, dim=1)
            all_probs.append(probs.cpu().numpy())
            all_labels.extend(targets.numpy().tolist())

    labels_array = np.array(all_labels)
    pred_probs = np.concatenate(all_probs, axis=0)

    report = validate_labels(labels_array, pred_probs)
    result = report.to_dict()

    logger.info(
        "Label validation: %d/%d issues (%.1f%%), avg_quality=%.3f",
        result["label_issues_found"],
        result["total_samples"],
        result["label_issue_rate"] * 100,
        result["avg_label_quality"],
    )

    # Log CleanLab metrics to MLflow for traceability
    if mlflow_run_id and mlflow_tracking_uri:
        from mlflow import MlflowClient

        client = MlflowClient(mlflow_tracking_uri)
        client.log_metric(mlflow_run_id, "label_issues_found", result["label_issues_found"])
        client.log_metric(mlflow_run_id, "avg_label_quality", result["avg_label_quality"])
        client.log_metric(mlflow_run_id, "label_issue_rate", result["label_issue_rate"])
        logger.info("Logged CleanLab metrics to MLflow run %s", mlflow_run_id)

    # Create Prefect artifact
    markdown = f"""## Label Validation Report (CleanLab)
| Metric | Value |
|--------|-------|
| Total Samples | {result["total_samples"]} |
| Label Issues Found | {result["label_issues_found"]} |
| Label Issue Rate | {result["label_issue_rate"]:.1%} |
| Avg Label Quality | {result["avg_label_quality"]:.3f} |
"""
    create_markdown_artifact(key="label-validation-report", markdown=markdown)

    return result


@task(name="ensure-data-available", retries=2, retry_delay_seconds=30)
def ensure_data_available(data_dir: str, verify: bool = True) -> Path:
    """Pull dataset from DVC remote if not present locally.

    Uses DVCManager Python API instead of subprocess calls.
    Optionally verifies data integrity after pull via checksum validation.

    Args:
        data_dir: Path to the dataset directory.
        verify: Whether to verify checksum after pull.

    Returns:
        Resolved dataset path.

    Raises:
        FileNotFoundError: If dataset directory and .dvc file are both missing.
        RuntimeError: If checksum verification fails after pull.
    """
    from src.core.data.versioning import DVCManager

    path = Path(data_dir)
    if path.exists():
        logger.info("Data already available at %s", path)
        return path

    dvc_file = Path(f"{data_dir}.dvc")
    if not dvc_file.exists():
        raise FileNotFoundError(
            f"Dataset not found at {path} and no DVC file at {dvc_file}. "
            "Run 'dvc add' first or provide the correct data path."
        )

    logger.info("Data not found locally, pulling from DVC remote...")
    manager = DVCManager()
    try:
        success = manager.pull(str(dvc_file))
        if not success:
            raise RuntimeError(f"DVC pull failed for {dvc_file}")

        if verify and not manager.verify_checksum(str(dvc_file)):
            raise RuntimeError(f"Checksum verification failed for {dvc_file}. Data may be corrupted or incomplete.")
        logger.info("DVC pull completed with integrity verification for %s", dvc_file)
    finally:
        manager.close()

    return path
