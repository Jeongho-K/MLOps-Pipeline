"""Data-Centric Active Learning Demo.

Runs 10 rounds of the data cleaning loop:
  1. CleanVision image quality check -> remove bad images
  2. Train model (short epochs, MLflow tracking)
  3. CleanLab label quality check -> remove bad labels
  4. Log metrics, create Prefect artifacts
  5. Repeat

Demonstrates that removing bad data (even though total data decreases)
leads to progressive improvement in model accuracy.

Usage:
    # Ensure services are running: make up && make seed
    # Prepare noisy data first:
    #   python examples/image_classification/prepare_noisy_data.py
    # Then run:
    python scripts/run_active_learning_demo.py

    # Or with custom settings:
    python scripts/run_active_learning_demo.py --rounds 5 --epochs 3
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import httpx
import mlflow
import mlflow.pytorch
import numpy as np
import pandas as pd
import torch
from mlflow import MlflowClient
from mlflow.models import infer_signature
from prefect import flow, task
from prefect.artifacts import create_markdown_artifact, create_table_artifact
from prefect.runtime import flow_run as flow_run_runtime
from prefect.transactions import transaction
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from src.data.preprocessing.transforms import get_eval_transforms, get_train_transforms
from src.data.validation.label_validator import validate_labels
from src.monitoring.evidently.drift_detector import detect_drift, push_drift_metrics
from src.training.models.classifier import create_classifier
from src.training.trainers.classification_trainer import _run_epoch, resolve_device

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@task(name="clean-images")
def clean_images_task(data_dir: str, round_num: int) -> dict[str, Any]:
    """Run CleanVision and remove problematic images.

    Args:
        data_dir: Path to dataset directory.
        round_num: Current Active Learning round number.

    Returns:
        Dict with cleaning results.
    """
    from cleanvision import Imagelab

    from src.data.validation.image_validator import validate_image_dataset

    train_dir = Path(data_dir) / "train"
    report = validate_image_dataset(train_dir)

    before_count = sum(1 for _ in train_dir.rglob("*.png"))

    imagelab = Imagelab(data_path=str(train_dir))
    imagelab.find_issues()

    issues_df = imagelab.issues
    issue_cols = [c for c in issues_df.columns if c.startswith("is_") and c.endswith("_issue")]
    has_issue = issues_df[issue_cols].any(axis=1)
    problematic = issues_df[has_issue].index.tolist()

    removed_count = 0
    for img_path in problematic:
        p = Path(img_path)
        if p.exists():
            p.unlink()
            removed_count += 1

    after_count = sum(1 for _ in train_dir.rglob("*.png"))

    result = {
        "round": round_num,
        "before_count": before_count,
        "removed_images": removed_count,
        "after_count": after_count,
        "health_score": report.health_score,
        "issues_found": report.issues_found,
    }

    markdown = f"""## Round {round_num}: Image Cleaning
| Metric | Value |
|--------|-------|
| Images Before | {before_count} |
| Images Removed | {removed_count} |
| Images After | {after_count} |
| Health Score | {report.health_score:.3f} |
"""
    create_markdown_artifact(key=f"image-clean-round-{round_num}", markdown=markdown)

    logger.info("Round %d image cleaning: removed %d/%d images", round_num, removed_count, before_count)
    return result


@task(name="train-round")
def train_round_task(
    data_dir: str,
    round_num: int,
    model_name: str,
    num_classes: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    experiment_name: str,
    mlflow_tracking_uri: str,
    registered_model_name: str,
    image_size: int = 224,
) -> dict[str, Any]:
    """Train model for one Active Learning round.

    Args:
        data_dir: Path to dataset directory.
        round_num: Current round number.
        model_name: Architecture name.
        num_classes: Number of classes.
        epochs: Training epochs per round.
        batch_size: Batch size.
        learning_rate: Learning rate.
        experiment_name: MLflow experiment name.
        mlflow_tracking_uri: MLflow URI.
        registered_model_name: Model registry name.
        image_size: Input image size.

    Returns:
        Dict with training metrics and model info.
    """
    device = resolve_device("auto")
    train_dir = Path(data_dir) / "train"
    val_dir = Path(data_dir) / "val"

    train_dataset = ImageFolder(str(train_dir), transform=get_train_transforms(image_size))
    val_dataset = ImageFolder(str(val_dir), transform=get_eval_transforms(image_size))

    pin_memory = device.type == "cuda"
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=0,
        pin_memory=pin_memory,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=pin_memory,
    )

    model = create_classifier(model_name, num_classes, pretrained=True)
    model = model.to(device)
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    mlflow.set_experiment(experiment_name)
    mlflow.pytorch.autolog(log_models=False, log_every_n_epoch=None)

    best_val_acc = 0.0
    model_version = None
    with mlflow.start_run(run_name=f"round-{round_num}") as run:
        # Tag with Prefect flow_run_id for cross-system traceability
        flow_run_id = flow_run_runtime.get_id() or ""
        if flow_run_id:
            mlflow.set_tag("prefect.flow_run_id", flow_run_id)
        mlflow.set_tag("round_number", str(round_num))

        mlflow.log_params(
            {
                "round": round_num,
                "model_name": model_name,
                "epochs": epochs,
                "batch_size": batch_size,
                "learning_rate": learning_rate,
                "train_samples": len(train_dataset),
                "val_samples": len(val_dataset),
                "device": str(device),
            }
        )

        for epoch in range(epochs):
            train_loss, train_acc = _run_epoch(
                model,
                train_loader,
                criterion,
                optimizer,
                device,
                training=True,
            )
            val_loss, val_acc = _run_epoch(
                model,
                val_loader,
                criterion,
                None,
                device,
                training=False,
            )

            mlflow.log_metrics(
                {
                    "train_loss": train_loss,
                    "train_accuracy": train_acc,
                    "val_loss": val_loss,
                    "val_accuracy": val_acc,
                },
                step=epoch,
            )

            if val_acc > best_val_acc:
                best_val_acc = val_acc

        mlflow.log_metrics(
            {
                "best_val_accuracy": best_val_acc,
                "round_number": round_num,
                "train_data_count": len(train_dataset),
            }
        )

        # Collect validation predictions for drift detection
        model.eval()
        val_preds_list: list[np.ndarray] = []
        with torch.no_grad():
            for images, _ in val_loader:
                outputs = model(images.to(device))
                probs = torch.softmax(outputs, dim=1)
                val_preds_list.append(probs.cpu().numpy())
        val_predictions = np.concatenate(val_preds_list, axis=0)

        # Log model with signature
        sample_input = torch.randn(1, 3, image_size, image_size)
        with torch.no_grad():
            sample_output = model(sample_input.to(device))
        signature = infer_signature(sample_input.numpy(), sample_output.cpu().numpy())

        model_info = mlflow.pytorch.log_model(
            model,
            name="model",
            signature=signature,
            input_example=sample_input.numpy(),
            registered_model_name=registered_model_name,
        )

        if model_info.registered_model_version:
            model_version = model_info.registered_model_version
            client = MlflowClient()
            client.set_registered_model_alias(
                registered_model_name,
                "challenger",
                model_version,
            )

        run_id = run.info.run_id

    return {
        "round": round_num,
        "best_val_accuracy": best_val_acc,
        "train_samples": len(train_dataset),
        "val_samples": len(val_dataset),
        "run_id": run_id,
        "model_version": model_version,
        "val_predictions": val_predictions,
    }


@task(name="clean-labels")
def clean_labels_task(
    data_dir: str,
    round_num: int,
    mlflow_tracking_uri: str,
    registered_model_name: str,
    num_classes: int,
    image_size: int = 224,
    max_remove_per_round: int = 100,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run CleanLab and remove likely mislabeled images.

    Args:
        data_dir: Path to dataset directory.
        round_num: Current round number.
        mlflow_tracking_uri: MLflow URI.
        registered_model_name: Model name in registry.
        num_classes: Number of classes.
        image_size: Input image size.
        max_remove_per_round: Maximum images to remove per round.
        run_id: If provided, log CleanLab metrics to this MLflow run.

    Returns:
        Dict with label cleaning results.
    """
    device = resolve_device("auto")

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    model_uri = f"models:/{registered_model_name}@challenger"
    model = mlflow.pytorch.load_model(model_uri)
    model = model.to(device)
    model.eval()

    train_dir = Path(data_dir) / "train"
    dataset = ImageFolder(str(train_dir), transform=get_eval_transforms(image_size))
    loader = DataLoader(dataset, batch_size=64, shuffle=False, num_workers=0)

    all_labels: list[int] = []
    all_probs: list[np.ndarray] = []

    with torch.no_grad():
        for images, targets in loader:
            outputs = model(images.to(device))
            probs = torch.softmax(outputs, dim=1)
            all_probs.append(probs.cpu().numpy())
            all_labels.extend(targets.numpy().tolist())

    all_paths = [sample[0] for sample in dataset.samples]
    labels_array = np.array(all_labels)
    pred_probs = np.concatenate(all_probs, axis=0)

    report = validate_labels(labels_array, pred_probs)
    before_count = len(dataset)

    issues_to_remove = report.issue_indices[:max_remove_per_round]
    removed_count = 0
    for idx in issues_to_remove:
        if idx < len(all_paths):
            p = Path(all_paths[idx])
            if p.exists():
                p.unlink()
                removed_count += 1

    after_count = sum(1 for _ in train_dir.rglob("*.png"))

    result = {
        "round": round_num,
        "total_label_issues": report.issues_found,
        "removed_labels": removed_count,
        "before_count": before_count,
        "after_count": after_count,
        "avg_label_quality": report.avg_label_quality,
        "label_issue_rate": report.issues_found / max(before_count, 1),
    }

    # Log CleanLab metrics to MLflow for traceability
    if run_id:
        client = MlflowClient(mlflow_tracking_uri)
        client.log_metric(run_id, "label_issues_found", report.issues_found)
        client.log_metric(run_id, "avg_label_quality", report.avg_label_quality)
        client.log_metric(run_id, "label_issue_rate", result["label_issue_rate"])
        logger.info("Logged CleanLab metrics to MLflow run %s", run_id)

    markdown = f"""## Round {round_num}: Label Cleaning (CleanLab)
| Metric | Value |
|--------|-------|
| Total Label Issues | {report.issues_found} |
| Labels Removed | {removed_count} |
| Samples Before | {before_count} |
| Samples After | {after_count} |
| Avg Label Quality | {report.avg_label_quality:.3f} |
| Label Issue Rate | {result["label_issue_rate"]:.1%} |
"""
    create_markdown_artifact(key=f"label-clean-round-{round_num}", markdown=markdown)

    logger.info(
        "Round %d label cleaning: %d issues found, %d removed",
        round_num,
        report.issues_found,
        removed_count,
    )
    return result


@task(name="reload-serving-model", retries=2, retry_delay_seconds=5)
def reload_serving_model_task(
    serving_url: str,
    model_name: str,
    model_version: str,
) -> dict[str, Any]:
    """Notify the serving API to reload the champion model.

    Args:
        serving_url: Base URL of the serving API (e.g. http://localhost:8000).
        model_name: Registered model name in MLflow.
        model_version: Model version string to reload.

    Returns:
        Dict with reload response status and message.
    """
    reload_url = f"{serving_url.rstrip('/')}/model/reload"
    payload = {"model_name": model_name, "model_version": model_version}

    with httpx.Client(timeout=30.0) as client:
        response = client.post(reload_url, json=payload)
        response.raise_for_status()
        result = response.json()

    logger.info(
        "Serving model reloaded: %s version %s -> %s",
        model_name,
        model_version,
        result.get("status"),
    )

    create_markdown_artifact(
        key="serving-reload",
        markdown=(
            f"## Serving Model Reloaded\n**Model:** {model_name} v{model_version}\n**Status:** {result.get('status')}\n"
        ),
    )

    return result


@task(name="check-drift")
def check_drift_task(
    current_predictions: np.ndarray,
    reference_predictions: np.ndarray | None,
    round_num: int,
    run_id: str = "",
    pushgateway_url: str = "http://localhost:9091",
) -> dict[str, Any]:
    """Compare prediction distributions between consecutive AL rounds.

    Args:
        current_predictions: Prediction probability array for current round.
        reference_predictions: Prediction probabilities for previous round, or None.
        round_num: Current AL round number.
        run_id: MLflow run ID for traceability in artifacts.
        pushgateway_url: URL of Prometheus Pushgateway.

    Returns:
        Dict with drift detection results, or empty dict if no reference.
    """
    if reference_predictions is None:
        logger.info("Round %d: No reference predictions for drift comparison (first round)", round_num)
        return {}

    columns = [f"class_{i}_prob" for i in range(current_predictions.shape[1])]
    ref_df = pd.DataFrame(reference_predictions, columns=columns)
    cur_df = pd.DataFrame(current_predictions, columns=columns)

    drift_result = detect_drift(ref_df, cur_df)

    try:
        push_drift_metrics(pushgateway_url, drift_result["drift_detected"], drift_result["drift_score"])
    except Exception:
        logger.warning("Failed to push drift metrics to Pushgateway", exc_info=True)

    create_markdown_artifact(
        key=f"drift-check-round-{round_num}",
        markdown=(
            f"## Round {round_num}: Drift Detection\n"
            f"**MLflow Run:** `{run_id}`\n\n"
            f"| Metric | Value |\n|--------|-------|\n"
            f"| Drift Detected | {drift_result['drift_detected']} |\n"
            f"| Drift Score | {drift_result['drift_score']:.4f} |\n"
            f"| Columns Checked | {len(drift_result.get('column_drifts', {}))} |\n"
        ),
    )

    logger.info(
        "Round %d drift check: detected=%s score=%.4f",
        round_num,
        drift_result["drift_detected"],
        drift_result["drift_score"],
    )
    return drift_result


@task(name="version-data")
def version_data_task(
    data_dir: str,
    round_num: int,
    run_id: str = "",
    mlflow_tracking_uri: str = "",
) -> dict[str, Any]:
    """Version the dataset with DVC after data cleaning.

    Uses DVCManager Python API for add/push/verify operations.
    Supports Prefect transaction rollback via on_rollback handler.

    Args:
        data_dir: Path to the dataset directory to track with DVC.
        round_num: Current AL round number.
        run_id: MLflow run ID to tag with data version hash.
        mlflow_tracking_uri: MLflow tracking URI for tagging.

    Returns:
        Dict with versioning results from VersioningResult.to_dict().
    """
    from src.data.versioning import DVCManager

    if not Path(".dvc").exists():
        logger.warning("DVC not initialized. Skipping data versioning.")
        return {"round": round_num, "dvc_added": False, "dvc_pushed": False, "data_hash": ""}

    manager = DVCManager()
    try:
        result = manager.version_round(
            data_dir=data_dir,
            round_num=round_num,
            run_id=run_id,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
    finally:
        manager.close()

    result_dict = result.to_dict()

    create_markdown_artifact(
        key=f"data-version-round-{round_num}",
        markdown=(
            f"## Round {round_num}: Data Versioning\n"
            f"**MLflow Run:** `{run_id}`\n\n"
            f"| Step | Result |\n|------|--------|\n"
            f"| DVC Add | {'OK' if result_dict['dvc_added'] else 'Failed'} |\n"
            f"| DVC Push | {'OK' if result_dict['dvc_pushed'] else 'Skipped'} |\n"
            f"| Checksum Verified | {'OK' if result_dict['checksum_verified'] else 'N/A'} |\n"
            f"| Data Hash | `{result_dict['data_hash'][:12]}...` |\n"
        ),
    )

    return result_dict


@version_data_task.on_rollback
def rollback_version_data(txn: transaction) -> None:
    """Rollback data to the previous DVC state on transaction failure."""
    from src.data.versioning import DVCManager

    data_dir = txn.get("data_dir", "")
    round_num = txn.get("round_num", "?")
    logger.warning("Rolling back data versioning for round %s", round_num)

    manager = DVCManager()
    try:
        manager.checkout(target=data_dir)
    finally:
        manager.close()


@task(name="snapshot-intermediate-data")
def snapshot_intermediate_data_task(
    data_dir: str,
    round_num: int,
    stage: str,
    previous_hash: str = "",
    cleaning_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture intermediate data state during an active learning round.

    Creates a local DVC snapshot (no push) for tracking data evolution
    within each round. Snapshots are chained via previous_hash.

    Args:
        data_dir: Path to the dataset directory.
        round_num: Current AL round number.
        stage: Stage name (e.g. "pre-clean", "post-image-clean", "post-label-clean").
        previous_hash: Hash from the previous snapshot for chain linking.
        cleaning_stats: Optional cleaning statistics to record.

    Returns:
        Dict with snapshot metadata from RoundSnapshot.to_dict().
    """
    from src.data.versioning import DVCConfig, DVCManager, RoundSnapshot

    config = DVCConfig(push_to_remote=False, verify_checksum=False)
    manager = DVCManager(config=config)
    try:
        data_hash = manager.add(data_dir)
    except (FileNotFoundError, RuntimeError):
        logger.warning("Round %d/%s: Snapshot failed for %s", round_num, stage, data_dir, exc_info=True)
        data_hash = ""
    finally:
        manager.close()

    train_dir = Path(data_dir) / "train"
    sample_count = sum(1 for _ in train_dir.rglob("*.png")) if train_dir.exists() else 0

    snapshot = RoundSnapshot(
        round_num=round_num,
        data_hash=data_hash,
        sample_count=sample_count,
        stage=stage,
        cleaning_stats=cleaning_stats or {},
        previous_hash=previous_hash,
    )

    logger.info(
        "Round %d/%s snapshot: hash=%s samples=%d",
        round_num,
        stage,
        data_hash[:12] if data_hash else "N/A",
        sample_count,
    )

    return snapshot.to_dict()


@flow(name="active-learning-demo", log_prints=True)
def active_learning_demo(
    data_dir: str = "data/raw/cifar10-noisy",
    rounds: int = 10,
    model_name: str = "resnet18",
    num_classes: int = 10,
    epochs_per_round: int = 3,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    experiment_name: str = "active-learning-demo",
    mlflow_tracking_uri: str = "http://localhost:5050",
    registered_model_name: str = "cifar10-active-learning",
    serving_url: str = "http://localhost:8000",
    pushgateway_url: str = "http://localhost:9091",
) -> list[dict]:
    """Run Data-Centric Active Learning loop.

    Each round: clean images -> train -> clean labels -> version data -> check drift.

    Args:
        data_dir: Path to noisy dataset.
        rounds: Number of Active Learning rounds.
        model_name: Model architecture.
        num_classes: Number of classes.
        epochs_per_round: Training epochs per round.
        batch_size: Batch size.
        learning_rate: Learning rate.
        experiment_name: MLflow experiment name.
        mlflow_tracking_uri: MLflow URI.
        registered_model_name: Model registry name.
        serving_url: Base URL of the serving API for auto-reload.
        pushgateway_url: Prometheus Pushgateway URL for drift metrics.

    Returns:
        List of per-round result dictionaries.
    """
    all_results: list[dict] = []
    best_accuracy = 0.0
    previous_predictions: np.ndarray | None = None
    last_data_hash = ""

    for round_num in range(1, rounds + 1):
        logger.info("=" * 60)
        logger.info("ACTIVE LEARNING ROUND %d/%d", round_num, rounds)
        logger.info("=" * 60)

        with transaction() as txn:
            txn.set("round_num", round_num)
            txn.set("data_dir", data_dir)

            # Snapshot: pre-clean state
            pre_snapshot = snapshot_intermediate_data_task(
                data_dir=data_dir,
                round_num=round_num,
                stage="pre-clean",
                previous_hash=last_data_hash,
            )

            # Step 1: Clean images
            image_result = clean_images_task(data_dir, round_num)

            # Snapshot: post-image-clean state
            post_image_snapshot = snapshot_intermediate_data_task(
                data_dir=data_dir,
                round_num=round_num,
                stage="post-image-clean",
                previous_hash=pre_snapshot.get("data_hash", ""),
                cleaning_stats={"images_removed": image_result.get("removed_images", 0)},
            )

            # Step 2: Train
            train_result = train_round_task(
                data_dir=data_dir,
                round_num=round_num,
                model_name=model_name,
                num_classes=num_classes,
                epochs=epochs_per_round,
                batch_size=batch_size,
                learning_rate=learning_rate,
                experiment_name=experiment_name,
                mlflow_tracking_uri=mlflow_tracking_uri,
                registered_model_name=registered_model_name,
            )

            run_id = train_result.get("run_id", "")

            # Step 3: Clean labels (skip round 1 to establish baseline)
            label_result: dict = {}
            if round_num > 1:
                label_result = clean_labels_task(
                    data_dir=data_dir,
                    round_num=round_num,
                    mlflow_tracking_uri=mlflow_tracking_uri,
                    registered_model_name=registered_model_name,
                    num_classes=num_classes,
                    run_id=run_id,
                )

                # Snapshot: post-label-clean state
                snapshot_intermediate_data_task(
                    data_dir=data_dir,
                    round_num=round_num,
                    stage="post-label-clean",
                    previous_hash=post_image_snapshot.get("data_hash", ""),
                    cleaning_stats={"labels_removed": label_result.get("removed_labels", 0)},
                )

            # Step 4: Version data with DVC (final, pushes to remote)
            version_result = version_data_task(
                data_dir=data_dir,
                round_num=round_num,
                run_id=run_id,
                mlflow_tracking_uri=mlflow_tracking_uri,
            )
            last_data_hash = version_result.get("data_hash", "")

        # Step 5: Check prediction drift between rounds (outside transaction)
        val_preds = train_result.get("val_predictions")
        drift_result = check_drift_task(
            current_predictions=val_preds,
            reference_predictions=previous_predictions,
            round_num=round_num,
            run_id=run_id,
            pushgateway_url=pushgateway_url,
        )
        previous_predictions = val_preds

        # Step 6: Promote to champion if best accuracy
        if train_result["best_val_accuracy"] > best_accuracy:
            best_accuracy = train_result["best_val_accuracy"]
            if train_result.get("model_version"):
                client = MlflowClient(mlflow_tracking_uri)
                client.set_registered_model_alias(
                    registered_model_name,
                    "champion",
                    train_result["model_version"],
                )
                logger.info(
                    "New champion! Round %d, accuracy=%.4f, version=%s",
                    round_num,
                    best_accuracy,
                    train_result["model_version"],
                )

                # Step 7: Notify serving API to reload champion model
                try:
                    reload_serving_model_task(
                        serving_url=serving_url,
                        model_name=registered_model_name,
                        model_version="@champion",
                    )
                except Exception:
                    logger.warning(
                        "Failed to reload serving model (server may not be running)",
                        exc_info=True,
                    )

        round_result = {
            "round": round_num,
            "accuracy": train_result["best_val_accuracy"],
            "train_samples": train_result["train_samples"],
            "images_removed": image_result.get("removed_images", 0),
            "labels_removed": label_result.get("removed_labels", 0),
            "health_score": image_result.get("health_score", 0),
            "label_issue_rate": label_result.get("label_issue_rate", 0),
            "drift_detected": drift_result.get("drift_detected", False),
            "drift_score": drift_result.get("drift_score", 0.0),
            "run_id": run_id,
        }
        all_results.append(round_result)

    # Create summary artifacts
    summary_table = [
        {
            "Round": r["round"],
            "Accuracy": f"{r['accuracy']:.4f}",
            "Train Samples": r["train_samples"],
            "Images Removed": r["images_removed"],
            "Labels Removed": r["labels_removed"],
            "Drift Score": f"{r.get('drift_score', 0):.4f}",
            "Run ID": r.get("run_id", "")[:8],
        }
        for r in all_results
    ]
    create_table_artifact(key="active-learning-summary", table=summary_table)

    first_acc = all_results[0]["accuracy"] if all_results else 0
    last_acc = all_results[-1]["accuracy"] if all_results else 0
    improvement = last_acc - first_acc
    markdown = f"""## Active Learning Summary ({rounds} rounds)
| Metric | Value |
|--------|-------|
| Initial Accuracy | {first_acc:.4f} |
| Final Accuracy | {last_acc:.4f} |
| Improvement | {improvement:+.4f} |
| Best Accuracy | {best_accuracy:.4f} |
| Initial Train Size | {all_results[0]["train_samples"] if all_results else "N/A"} |
| Final Train Size | {all_results[-1]["train_samples"] if all_results else "N/A"} |
"""
    create_markdown_artifact(key="active-learning-final-summary", markdown=markdown)

    logger.info(
        "Active Learning complete! %d rounds, accuracy: %.4f -> %.4f (delta %+.4f)",
        rounds,
        first_acc,
        last_acc,
        improvement,
    )

    return all_results


def main() -> None:
    """Parse arguments and run Active Learning demo."""
    parser = argparse.ArgumentParser(description="Data-Centric Active Learning Demo")
    parser.add_argument("--data-dir", default="data/raw/cifar10-noisy", help="Dataset path")
    parser.add_argument("--rounds", type=int, default=10, help="Number of AL rounds")
    parser.add_argument("--epochs", type=int, default=3, help="Epochs per round")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--model", default="resnet18", help="Model architecture")
    parser.add_argument("--mlflow-uri", default="http://localhost:5050", help="MLflow URI")
    parser.add_argument("--experiment", default="active-learning-demo", help="MLflow experiment")
    parser.add_argument("--model-name", default="cifar10-active-learning", help="Registry name")
    parser.add_argument("--serving-url", default="http://localhost:8000", help="Serving API URL")
    parser.add_argument("--pushgateway-url", default="http://localhost:9091", help="Pushgateway URL")
    args = parser.parse_args()

    active_learning_demo(
        data_dir=args.data_dir,
        rounds=args.rounds,
        model_name=args.model,
        num_classes=10,
        epochs_per_round=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        experiment_name=args.experiment,
        mlflow_tracking_uri=args.mlflow_uri,
        registered_model_name=args.model_name,
        serving_url=args.serving_url,
        pushgateway_url=args.pushgateway_url,
    )


if __name__ == "__main__":
    main()
