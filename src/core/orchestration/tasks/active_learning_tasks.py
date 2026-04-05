"""Prefect tasks for Active Learning pipeline operations.

Tasks for fetching uncertain predictions, selecting samples for labeling,
creating Label Studio tasks, and managing pseudo-label accumulation.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, timedelta

import boto3
from prefect import task

logger = logging.getLogger(__name__)


@task(name="fetch-uncertain-predictions", retries=2, retry_delay_seconds=30)
def fetch_uncertain_predictions(
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    bucket: str,
    lookback_days: int = 1,
) -> list[dict]:
    """Fetch prediction logs filtered to routing_decision == 'human_review'.

    Reads JSONL files from ``s3://{bucket}/{date}/*.jsonl`` for the last N days.
    Filters to predictions where ``routing_decision == "human_review"``.

    Args:
        s3_endpoint: S3-compatible endpoint URL (e.g. ``http://minio:9000``).
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        bucket: S3 bucket name containing prediction logs.
        lookback_days: Number of past days to fetch logs for.

    Returns:
        List of prediction log dicts with routing_decision == "human_review".
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
    )

    today = date.today()
    uncertain: list[dict] = []

    paginator = client.get_paginator("list_objects_v2")

    for offset in range(lookback_days):
        day = today - timedelta(days=offset)
        prefix = f"{day.isoformat()}/"

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".jsonl"):
                    continue
                body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
                for line in body.decode("utf-8").strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get("routing_decision") == "human_review":
                        uncertain.append(record)

    logger.info(
        "Fetched %d uncertain predictions from the last %d day(s).",
        len(uncertain),
        lookback_days,
    )
    return uncertain


@task(name="select-samples-for-labeling")
def select_samples_for_labeling(
    predictions: list[dict],
    max_samples: int = 100,
) -> list[dict]:
    """Select top-K most uncertain samples for labeling.

    Sorts by ``uncertainty_score`` descending and takes the top ``max_samples``.

    Args:
        predictions: List of prediction log dicts with ``uncertainty_score``.
        max_samples: Maximum number of samples to select.

    Returns:
        List of the most uncertain prediction dicts, up to max_samples.
    """
    sorted_preds = sorted(
        predictions,
        key=lambda p: p.get("uncertainty_score", 0.0),
        reverse=True,
    )
    selected = sorted_preds[:max_samples]
    logger.info(
        "Selected %d/%d samples for labeling (max_samples=%d).",
        len(selected),
        len(predictions),
        max_samples,
    )
    return selected


@task(name="create-labeling-tasks", retries=2, retry_delay_seconds=30)
def create_labeling_tasks(
    samples: list[dict],
    label_studio_url: str,
    label_studio_api_key: str,
    label_studio_project_id: int,
) -> dict:
    """Create labeling tasks in Label Studio via LabelStudioBridge.

    Args:
        samples: List of prediction dicts to create as labeling tasks.
        label_studio_url: Label Studio API base URL.
        label_studio_api_key: Label Studio API token.
        label_studio_project_id: Label Studio project ID.

    Returns:
        Dict with ``tasks_created`` count and ``project_id``.
    """
    from src.core.active_learning.labeling.bridge import LabelStudioBridge

    if not samples:
        logger.info("No samples to create labeling tasks for.")
        return {"tasks_created": 0, "project_id": label_studio_project_id}

    bridge = LabelStudioBridge(
        base_url=label_studio_url,
        api_key=label_studio_api_key,
        project_id=label_studio_project_id,
    )
    try:
        result = bridge.create_tasks(samples)
        tasks_created = len(result) if isinstance(result, list) else 1
        logger.info(
            "Created %d labeling tasks in project %d.",
            tasks_created,
            label_studio_project_id,
        )
        return {"tasks_created": tasks_created, "project_id": label_studio_project_id}
    finally:
        bridge.close()


@task(name="fetch-accumulated-samples", retries=2, retry_delay_seconds=30)
def fetch_accumulated_samples(
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    bucket: str,
    prefix: str = "accumulated/",
) -> list[dict]:
    """Fetch all accumulated pseudo-label JSONL files from S3.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        bucket: S3 bucket name for accumulated pseudo-labels.
        prefix: S3 key prefix for accumulated data.

    Returns:
        List of pseudo-label sample dicts.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
    )

    samples: list[dict] = []
    paginator = client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".jsonl"):
                continue
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            for line in body.decode("utf-8").strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                record["_s3_key"] = key
                samples.append(record)

    logger.info(
        "Fetched %d accumulated pseudo-label samples from s3://%s/%s.",
        len(samples),
        bucket,
        prefix,
    )
    return samples


@task(name="validate-accumulation-quality")
def validate_accumulation_quality(
    samples: list[dict],
    existing_data_count: int,
    max_pseudo_label_ratio: float = 0.3,
    min_samples: int = 50,
) -> dict:
    """Quality gate: validate pseudo-label quality before merging.

    Checks:
        - Minimum sample count
        - Class distribution (no single class > 80%)
        - Pseudo-label ratio vs existing data

    Args:
        samples: List of accumulated pseudo-label sample dicts.
        existing_data_count: Number of existing training samples.
        max_pseudo_label_ratio: Maximum pseudo-label ratio in total training data.
        min_samples: Minimum number of accumulated samples required.

    Returns:
        Dict with ``passed`` (bool), ``reason`` (str), and ``stats`` (dict).
    """
    num_samples = len(samples)

    # Check minimum sample count
    if num_samples < min_samples:
        reason = f"Insufficient samples: {num_samples} < {min_samples}"
        logger.warning("Quality gate FAILED: %s", reason)
        return {
            "passed": False,
            "reason": reason,
            "stats": {"num_samples": num_samples},
        }

    # Check class distribution
    class_counts = Counter(s.get("predicted_class") for s in samples)
    total = sum(class_counts.values())
    max_class_ratio = max(class_counts.values()) / total if total > 0 else 0.0
    dominant_class = max(class_counts, key=class_counts.get)  # type: ignore[arg-type]

    if max_class_ratio > 0.8:
        reason = f"Class imbalance: class '{dominant_class}' has {max_class_ratio:.1%} of samples (threshold: 80%)"
        logger.warning("Quality gate FAILED: %s", reason)
        return {
            "passed": False,
            "reason": reason,
            "stats": {
                "num_samples": num_samples,
                "class_distribution": dict(class_counts),
                "max_class_ratio": max_class_ratio,
            },
        }

    # Check pseudo-label ratio
    total_after_merge = existing_data_count + num_samples
    pseudo_ratio = num_samples / total_after_merge if total_after_merge > 0 else 0.0

    if pseudo_ratio > max_pseudo_label_ratio:
        reason = (
            f"Pseudo-label ratio too high: {pseudo_ratio:.1%} > {max_pseudo_label_ratio:.1%} "
            f"({num_samples} pseudo / {total_after_merge} total)"
        )
        logger.warning("Quality gate FAILED: %s", reason)
        return {
            "passed": False,
            "reason": reason,
            "stats": {
                "num_samples": num_samples,
                "existing_data_count": existing_data_count,
                "pseudo_ratio": pseudo_ratio,
                "class_distribution": dict(class_counts),
            },
        }

    logger.info(
        "Quality gate PASSED: %d samples, ratio=%.1f%%, max_class=%.1f%%.",
        num_samples,
        pseudo_ratio * 100,
        max_class_ratio * 100,
    )
    return {
        "passed": True,
        "reason": "All checks passed",
        "stats": {
            "num_samples": num_samples,
            "existing_data_count": existing_data_count,
            "pseudo_ratio": pseudo_ratio,
            "max_class_ratio": max_class_ratio,
            "class_distribution": dict(class_counts),
        },
    }


@task(name="cleanup-accumulated", retries=1, retry_delay_seconds=10)
def cleanup_accumulated(
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    bucket: str,
    prefix: str = "accumulated/",
    keys: list[str] | None = None,
) -> int:
    """Delete processed JSONL files from S3 accumulation prefix.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        bucket: S3 bucket name for accumulated pseudo-labels.
        prefix: S3 key prefix for accumulated data.
        keys: Specific S3 keys to delete. If None, deletes all .jsonl under prefix.

    Returns:
        Number of objects deleted.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
    )

    if keys is None:
        # List all .jsonl files under prefix
        keys_to_delete: list[str] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".jsonl"):
                    keys_to_delete.append(obj["Key"])
    else:
        keys_to_delete = keys

    if not keys_to_delete:
        logger.info("No accumulated files to cleanup.")
        return 0

    # Delete in batches of 1000 (S3 limit)
    deleted = 0
    for i in range(0, len(keys_to_delete), 1000):
        batch = keys_to_delete[i : i + 1000]
        delete_objects = [{"Key": k} for k in batch]
        response = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": delete_objects},
        )
        errors = response.get("Errors", [])
        if errors:
            logger.warning("Failed to delete %d objects: %s", len(errors), errors[:3])
        deleted += len(batch) - len(errors)

    logger.info("Deleted %d accumulated files from s3://%s/%s.", deleted, bucket, prefix)
    return deleted
