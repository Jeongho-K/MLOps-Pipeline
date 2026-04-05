"""Prefect tasks for Phase B continuous training operations.

Tasks for quality gates (G2, G3), champion model promotion,
round tracking, and training data integration.
"""

from __future__ import annotations

import json
import logging
import random
import shutil
from pathlib import Path

import boto3
import mlflow
from mlflow import MlflowClient
from prefect import task
from prefect.artifacts import create_markdown_artifact

logger = logging.getLogger(__name__)


@task(name="check-training-quality")
def check_training_quality(
    metrics: dict[str, float],
    min_val_accuracy: float = 0.7,
    max_overfit_gap: float = 0.15,
) -> dict:
    """G2 quality gate: validate training metrics before model registration.

    Checks:
        - Validation accuracy meets minimum threshold.
        - Overfitting gap (val_loss - train_loss) is within acceptable range.

    Args:
        metrics: Training metrics dict with 'best_val_accuracy', 'train_loss', 'val_loss'.
        min_val_accuracy: Minimum validation accuracy to pass.
        max_overfit_gap: Maximum allowed val_loss - train_loss gap.

    Returns:
        Dict with 'passed' (bool), 'reason' (str), and 'checks' (dict).
    """
    checks: dict[str, dict] = {}
    failed_reasons: list[str] = []

    # Check 1: Minimum validation accuracy
    best_val_acc = metrics.get("best_val_accuracy", 0.0)
    acc_passed = best_val_acc >= min_val_accuracy
    checks["val_accuracy"] = {
        "passed": acc_passed,
        "value": best_val_acc,
        "threshold": min_val_accuracy,
    }
    if not acc_passed:
        failed_reasons.append(f"best_val_accuracy ({best_val_acc:.4f}) < min ({min_val_accuracy:.4f})")

    # Check 2: Overfitting gap
    train_loss = metrics.get("train_loss")
    val_loss = metrics.get("val_loss")
    if train_loss is not None and val_loss is not None:
        overfit_gap = val_loss - train_loss
        gap_passed = overfit_gap <= max_overfit_gap
        checks["overfit_gap"] = {
            "passed": gap_passed,
            "value": overfit_gap,
            "threshold": max_overfit_gap,
            "train_loss": train_loss,
            "val_loss": val_loss,
        }
        if not gap_passed:
            failed_reasons.append(f"overfit gap ({overfit_gap:.4f}) > max ({max_overfit_gap:.4f})")
    else:
        checks["overfit_gap"] = {"passed": True, "value": None, "reason": "train_loss not available, skipped"}

    passed = len(failed_reasons) == 0
    reason = "; ".join(failed_reasons) if failed_reasons else "All checks passed"

    status = "PASSED" if passed else "FAILED"
    logger.info("G2 Training Quality Gate %s: %s", status, reason)

    # Create Prefect artifact
    check_rows = ""
    for name, check in checks.items():
        result_str = "PASS" if check["passed"] else "FAIL"
        check_rows += f"| {name} | {check.get('value', 'N/A')} | {check.get('threshold', 'N/A')} | {result_str} |\n"

    markdown = f"""## G2 Training Quality Gate: {status}
| Check | Value | Threshold | Result |
|-------|-------|-----------|--------|
{check_rows}
**Reason:** {reason}
"""
    create_markdown_artifact(key="g2-training-quality-gate", markdown=markdown)

    return {"passed": passed, "reason": reason, "checks": checks}


@task(name="check-champion-gate", retries=1, retry_delay_seconds=10)
def check_champion_gate(
    challenger_metrics: dict[str, float],
    registered_model_name: str,
    champion_metric: str = "best_val_accuracy",
    champion_margin: float = 0.0,
    mlflow_tracking_uri: str = "http://localhost:5000",
) -> dict:
    """G3 quality gate: compare challenger model against current champion.

    Loads the champion model's run metrics from MLflow and compares
    against the challenger's metrics. If no champion exists, auto-promotes.

    Args:
        challenger_metrics: Training metrics from the challenger model.
        registered_model_name: MLflow registered model name.
        champion_metric: Metric name to compare (must exist in both runs).
        champion_margin: Challenger must exceed champion by this margin.
        mlflow_tracking_uri: MLflow tracking server URI.

    Returns:
        Dict with 'passed' (bool), 'reason' (str), 'champion_value',
        'challenger_value', and 'comparison' details.
    """
    from mlflow.exceptions import MlflowException

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    client = MlflowClient()

    challenger_value = challenger_metrics.get(champion_metric)
    if challenger_value is None:
        reason = f"Challenger metrics missing key '{champion_metric}'"
        logger.error("G3 Champion Gate FAILED: %s", reason)
        return {"passed": False, "reason": reason, "challenger_value": None, "champion_value": None}

    # Try to load champion model
    try:
        champion_version = client.get_model_version_by_alias(registered_model_name, "champion")
        champion_run = client.get_run(champion_version.run_id)
        champion_value = champion_run.data.metrics.get(champion_metric)

        if champion_value is None:
            reason = f"Champion run {champion_version.run_id} missing metric '{champion_metric}', auto-promoting"
            logger.warning("G3 Champion Gate: %s", reason)
            return {
                "passed": True,
                "reason": reason,
                "challenger_value": challenger_value,
                "champion_value": None,
                "champion_version": champion_version.version,
            }

    except MlflowException:
        logger.info("No champion model found for '%s'. Auto-promoting challenger.", registered_model_name)
        return {
            "passed": True,
            "reason": "No existing champion — auto-promoting",
            "challenger_value": challenger_value,
            "champion_value": None,
        }

    # Compare
    passed = challenger_value > champion_value + champion_margin
    if passed:
        reason = (
            f"Challenger ({challenger_value:.4f}) > champion ({champion_value:.4f}) + margin ({champion_margin:.4f})"
        )
    else:
        reason = (
            f"Challenger ({challenger_value:.4f}) did not exceed champion ({champion_value:.4f}) "
            f"+ margin ({champion_margin:.4f})"
        )

    status = "PASSED" if passed else "FAILED"
    logger.info("G3 Champion Gate %s: %s", status, reason)

    # Create Prefect artifact
    markdown = f"""## G3 Champion Gate: {status}
| Metric | Champion | Challenger | Margin | Result |
|--------|----------|------------|--------|--------|
| {champion_metric} | {champion_value:.4f} | {challenger_value:.4f} | {champion_margin:.4f} | {status} |

**Reason:** {reason}
"""
    create_markdown_artifact(key="g3-champion-gate", markdown=markdown)

    return {
        "passed": passed,
        "reason": reason,
        "challenger_value": challenger_value,
        "champion_value": champion_value,
        "champion_version": champion_version.version,
    }


@task(name="promote-to-champion", retries=2, retry_delay_seconds=10)
def promote_to_champion(
    registered_model_name: str,
    mlflow_tracking_uri: str = "http://localhost:5000",
) -> dict:
    """Promote the current challenger model to champion in MLflow registry.

    Sets the @champion alias on the model version that currently has
    the @challenger alias.

    Args:
        registered_model_name: MLflow registered model name.
        mlflow_tracking_uri: MLflow tracking server URI.

    Returns:
        Dict with promoted version info.
    """
    mlflow.set_tracking_uri(mlflow_tracking_uri)
    client = MlflowClient()

    # Get challenger version
    challenger_version = client.get_model_version_by_alias(registered_model_name, "challenger")
    version = challenger_version.version

    # Set champion alias
    client.set_registered_model_alias(
        name=registered_model_name,
        alias="champion",
        version=version,
    )

    logger.info(
        "Promoted %s version %s from challenger to champion.",
        registered_model_name,
        version,
    )

    markdown = f"""## Champion Promotion
| Field | Value |
|-------|-------|
| Model | {registered_model_name} |
| Version | {version} |
| Run ID | {challenger_version.run_id} |
"""
    create_markdown_artifact(key="champion-promotion", markdown=markdown)

    return {
        "registered_model_name": registered_model_name,
        "version": version,
        "run_id": challenger_version.run_id,
    }


@task(name="resolve-round-number", retries=2, retry_delay_seconds=5)
def resolve_round_number(
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    bucket: str = "active-learning",
    state_key: str = "rounds/round_state.json",
    explicit_round: int | None = None,
) -> int:
    """Resolve and increment the current AL round number.

    Reads the round state from S3, increments, and writes back.
    If no state exists, initializes to round 1.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        bucket: S3 bucket for round state.
        state_key: S3 key for round state JSON file.
        explicit_round: If provided, use this round number instead of auto-incrementing.

    Returns:
        The current round number.
    """
    if explicit_round is not None:
        logger.info("Using explicit round number: %d", explicit_round)
        return explicit_round

    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
    )

    # Read current state
    current_round = 0
    try:
        body = client.get_object(Bucket=bucket, Key=state_key)["Body"].read()
        state = json.loads(body.decode("utf-8"))
        current_round = state.get("round", 0)
    except client.exceptions.NoSuchKey:
        logger.info("No round state found. Initializing to round 1.")
    except Exception:
        logger.warning("Failed to read round state, starting from round 1.", exc_info=True)

    # Increment
    new_round = current_round + 1

    # Write back
    new_state = json.dumps({"round": new_round})
    client.put_object(Bucket=bucket, Key=state_key, Body=new_state.encode("utf-8"))

    logger.info("AL round: %d → %d", current_round, new_round)
    return new_round


@task(name="integrate-training-data", retries=1, retry_delay_seconds=30, timeout_seconds=1800)
def integrate_training_data(
    label_studio_url: str,
    label_studio_api_key: str,
    label_studio_project_id: int,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    accumulation_bucket: str = "active-learning",
    accumulation_prefix: str = "accumulated/",
    output_dir: str = "data/merged",
    train_val_split: float = 0.8,
    seed: int = 42,
) -> dict:
    """Merge pseudo-labels and human annotations into ImageFolder format.

    Downloads human-labeled annotations from Label Studio and pseudo-labeled
    samples from S3, then writes both into a unified training dataset
    in ImageFolder format: ``{output_dir}/train/{class}/`` and
    ``{output_dir}/val/{class}/``.

    Args:
        label_studio_url: Label Studio API base URL.
        label_studio_api_key: Label Studio API token.
        label_studio_project_id: Label Studio project ID.
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        accumulation_bucket: S3 bucket for pseudo-labels.
        accumulation_prefix: S3 key prefix for pseudo-labels.
        output_dir: Output directory for merged ImageFolder dataset.
        train_val_split: Fraction of data for training (rest for validation).
        seed: Random seed for reproducible train/val split.

    Returns:
        Dict with sample counts by source and class.
    """
    from src.core.active_learning.labeling.bridge import LabelStudioBridge

    output_path = Path(output_dir)

    # Clean output directory for fresh merge
    if output_path.exists():
        shutil.rmtree(output_path)

    train_dir = output_path / "train"
    val_dir = output_path / "val"
    train_dir.mkdir(parents=True)
    val_dir.mkdir(parents=True)

    s3_client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
    )

    # Collect all samples with (image_bytes, class_name, source) tuples
    samples: list[tuple[bytes, str, str]] = []

    # --- Path 1: Human-labeled annotations from Label Studio ---
    human_count = 0
    human_fetch_failed = False
    try:
        bridge = LabelStudioBridge(
            base_url=label_studio_url,
            api_key=label_studio_api_key,
            project_id=label_studio_project_id,
        )
        try:
            annotations = bridge.get_completed_annotations(label_studio_project_id)
        finally:
            bridge.close()

        for annotation in annotations:
            image_url = _extract_image_url(annotation)
            class_name = _extract_class_label(annotation)

            if not image_url or not class_name:
                logger.debug("Skipping annotation %s: missing image or label.", annotation.get("id"))
                continue

            image_bytes = _download_image(s3_client, image_url, s3_endpoint, accumulation_bucket)
            if image_bytes:
                samples.append((image_bytes, class_name, "human_label"))
                human_count += 1

    except Exception:
        human_fetch_failed = True
        logger.warning("Failed to fetch human annotations from Label Studio.", exc_info=True)

    # --- Path 2: Auto-accumulated pseudo-labels from S3 ---
    pseudo_count = 0
    pseudo_fetch_failed = False
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=accumulation_bucket, Prefix=accumulation_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".jsonl"):
                    continue
                body = s3_client.get_object(Bucket=accumulation_bucket, Key=key)["Body"].read()
                for line in body.decode("utf-8").strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    class_name = record.get("class_name") or str(record.get("predicted_class", "unknown"))
                    image_ref = record.get("image_ref", "")

                    if not image_ref:
                        continue

                    image_bytes = _download_image(s3_client, image_ref, s3_endpoint, accumulation_bucket)
                    if image_bytes:
                        samples.append((image_bytes, class_name, "pseudo_label"))
                        pseudo_count += 1

    except Exception:
        pseudo_fetch_failed = True
        logger.warning("Failed to fetch pseudo-labels from S3.", exc_info=True)

    # If both data sources failed, raise so the pipeline retries rather than
    # silently treating an infrastructure outage as "no data available".
    if human_fetch_failed and pseudo_fetch_failed:
        raise RuntimeError(
            "Both data sources (Label Studio and S3 pseudo-labels) failed. "
            "Cannot determine if data is available. Check connectivity."
        )

    if not samples:
        logger.warning("No samples collected for data integration.")
        return {
            "total_samples": 0,
            "human_labeled": 0,
            "pseudo_labeled": 0,
            "classes": {},
        }

    # --- Stratified train/val split ---
    rng = random.Random(seed)
    rng.shuffle(samples)

    # Group by class for stratified split
    class_samples: dict[str, list[tuple[bytes, str, str]]] = {}
    for sample in samples:
        cls = sample[1]
        class_samples.setdefault(cls, []).append(sample)

    class_counts: dict[str, dict[str, int]] = {}
    total_written = 0

    for cls, cls_list in class_samples.items():
        split_idx = max(1, int(len(cls_list) * train_val_split))
        train_samples = cls_list[:split_idx]
        val_samples = cls_list[split_idx:]

        # Ensure at least 1 val sample
        if not val_samples and len(train_samples) > 1:
            val_samples = [train_samples.pop()]

        class_train_dir = train_dir / cls
        class_val_dir = val_dir / cls
        class_train_dir.mkdir(parents=True, exist_ok=True)
        class_val_dir.mkdir(parents=True, exist_ok=True)

        for i, (img_bytes, _, source) in enumerate(train_samples):
            filepath = class_train_dir / f"{source}_{i:06d}.jpg"
            filepath.write_bytes(img_bytes)
            total_written += 1

        for i, (img_bytes, _, source) in enumerate(val_samples):
            filepath = class_val_dir / f"{source}_{i:06d}.jpg"
            filepath.write_bytes(img_bytes)
            total_written += 1

        class_counts[cls] = {
            "train": len(train_samples),
            "val": len(val_samples),
        }

    logger.info(
        "Data integration complete: %d total (%d human, %d pseudo) across %d classes.",
        total_written,
        human_count,
        pseudo_count,
        len(class_counts),
    )

    result = {
        "total_samples": total_written,
        "human_labeled": human_count,
        "pseudo_labeled": pseudo_count,
        "classes": class_counts,
        "output_dir": str(output_path),
    }

    # Create Prefect artifact
    class_rows = ""
    for cls, counts in class_counts.items():
        class_rows += f"| {cls} | {counts['train']} | {counts['val']} |\n"

    markdown = f"""## Data Integration Summary
| Source | Count |
|--------|-------|
| Human-labeled | {human_count} |
| Pseudo-labeled | {pseudo_count} |
| **Total** | **{total_written}** |

### Per-Class Distribution
| Class | Train | Val |
|-------|-------|-----|
{class_rows}"""
    create_markdown_artifact(key="data-integration-summary", markdown=markdown)

    return result


def _extract_image_url(annotation: dict) -> str | None:
    """Extract image URL from a Label Studio annotation.

    Args:
        annotation: Label Studio annotation dict.

    Returns:
        Image URL string or None.
    """
    task_data = annotation.get("data", {})
    return task_data.get("image") or task_data.get("image_url")


def _extract_class_label(annotation: dict) -> str | None:
    """Extract the chosen class label from a Label Studio annotation.

    Handles the standard image classification format with <Choices> tag.

    Args:
        annotation: Label Studio annotation dict.

    Returns:
        Class label string or None.
    """
    annotations_list = annotation.get("annotations", [])
    if not annotations_list:
        return None

    # Take the most recent annotation
    latest = annotations_list[-1]
    results = latest.get("result", [])

    for result in results:
        value = result.get("value", {})
        choices = value.get("choices", [])
        if choices:
            return choices[0]

    return None


def _download_image(
    s3_client: boto3.client,
    image_ref: str,
    s3_endpoint: str,
    default_bucket: str,
) -> bytes | None:
    """Download an image from S3 or a URL.

    Handles both S3 keys and full S3/HTTP URLs.

    Args:
        s3_client: Boto3 S3 client.
        image_ref: S3 key, s3:// URL, or HTTP URL.
        s3_endpoint: S3 endpoint for URL resolution.
        default_bucket: Default S3 bucket if not specified in URL.

    Returns:
        Image bytes or None if download fails.
    """
    try:
        if image_ref.startswith("s3://"):
            # Parse s3://bucket/key
            parts = image_ref[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
        elif image_ref.startswith("http"):
            # HTTP URL — try to download via httpx
            import httpx

            response = httpx.get(image_ref, timeout=30)
            response.raise_for_status()
            return response.content
        else:
            # Assume it's an S3 key in the default bucket
            bucket = default_bucket
            key = image_ref

        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return body
    except Exception:
        logger.debug("Failed to download image: %s", image_ref, exc_info=True)
        return None
