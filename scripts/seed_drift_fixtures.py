"""Seed MinIO with reference + current prediction logs for drift E2E tests.

The monitoring pipeline reads reference from ``prediction-logs/reference/baseline.jsonl``
and current from ``prediction-logs/{YYYY-MM-DD}/*.jsonl``. This script generates
three fixtures (reference, medium-drift current, high-drift current) using the
same synthesis pattern as ``run_evidently_demo.py`` and uploads one of them to
the current-day prefix based on ``--severity``.

Usage (from inside a uv-managed shell with MinIO reachable at http://localhost:9000):
    uv run python scripts/seed_drift_fixtures.py --severity high
    uv run python scripts/seed_drift_fixtures.py --severity medium
    uv run python scripts/seed_drift_fixtures.py --severity none   # clears current prefix
"""

from __future__ import annotations

import argparse
import io
import json
import logging
from datetime import date
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    import pandas as pd

import numpy as np
import pandas as pd_runtime  # runtime alias: we only TYPE_CHECKING-import pd above

from scripts.run_evidently_demo import CLASSES, generate_prediction_data


def _deterministic_medium_current() -> pd_runtime.DataFrame:
    """Produce a current batch whose predicted_class column is byte-identical
    to the reference (no drift there) but whose confidence column is shifted
    downward (drift). With 2 total columns this yields drift_score=0.5 which
    lands inside the G5 MEDIUM band (0.3 ≤ score < 0.6), avoiding the HIGH
    path that the statistical sensitivity of Evidently otherwise triggers."""
    # Build the exact same class sequence the reference uses. Must mirror
    # run_evidently_demo.generate_prediction_data — same seed, same uniform
    # probability list (p=None and p=[0.1]*10 are NOT bit-identical in
    # numpy's RandomState.choice implementation).
    rng_ref = np.random.RandomState(42)
    uniform_p = [1.0 / len(CLASSES)] * len(CLASSES)
    predicted_classes = rng_ref.choice(len(CLASSES), size=REFERENCE_N, p=uniform_p)

    # Lower-confidence regime with a separate rng.
    rng_conf = np.random.RandomState(11)
    confidences = np.clip(rng_conf.normal(0.65, 0.18, REFERENCE_N), 0.1, 1.0)

    return pd_runtime.DataFrame(
        {"predicted_class": predicted_classes, "confidence": confidences}
    )

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("seed_drift_fixtures")

BUCKET = "prediction-logs"
REFERENCE_KEY = "reference/baseline.jsonl"
S3_ENDPOINT = "http://localhost:9000"
S3_ACCESS_KEY = "minioadmin"
S3_SECRET_KEY = "minioadmin123"

# Balanced reference: uniform class distribution, high confidence.
REFERENCE_N = 500

# HIGH drift: strong class skew + confidence collapse.
HIGH_DRIFT_DISTRIBUTION = [0.45, 0.45, 0.02, 0.02, 0.02, 0.02, 0.0, 0.0, 0.01, 0.01]
HIGH_DRIFT_CONF_MEAN = 0.55
HIGH_DRIFT_CONF_STD = 0.18

# MEDIUM drift: predicted_class stays balanced (no drift in that column), only
# confidence drifts — with 2 total columns this yields drift_score=0.5 which
# falls inside the G5 MEDIUM band (0.3 ≤ score < 0.6) rather than triggering
# HIGH rollback.
MEDIUM_DRIFT_DISTRIBUTION: list[float] | None = None  # balanced → no class drift
MEDIUM_DRIFT_CONF_MEAN = 0.65
MEDIUM_DRIFT_CONF_STD = 0.18


def _client() -> boto3.client:
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )


def _ensure_bucket(client: boto3.client) -> None:
    try:
        client.head_bucket(Bucket=BUCKET)
    except ClientError:
        logger.info("Creating bucket %s", BUCKET)
        client.create_bucket(Bucket=BUCKET)


def _to_jsonl(df: pd.DataFrame) -> bytes:
    """Convert DataFrame rows to JSONL bytes with the monitoring pipeline's schema."""
    lines: list[str] = []
    for record in df.to_dict(orient="records"):
        payload = {
            "predicted_class": CLASSES[int(record["predicted_class"])],
            "confidence": float(record["confidence"]),
        }
        lines.append(json.dumps(payload))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _clear_today_prefix(client: boto3.client) -> None:
    prefix = f"{date.today().isoformat()}/"
    resp = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    for obj in resp.get("Contents", []) or []:
        client.delete_object(Bucket=BUCKET, Key=obj["Key"])
        logger.info("Deleted s3://%s/%s", BUCKET, obj["Key"])


def _upload_reference(client: boto3.client) -> None:
    reference_df = generate_prediction_data(
        n_samples=REFERENCE_N,
        confidence_mean=0.88,
        confidence_std=0.08,
        seed=42,
    )
    payload = _to_jsonl(reference_df)
    client.put_object(
        Bucket=BUCKET,
        Key=REFERENCE_KEY,
        Body=io.BytesIO(payload),
        ContentType="application/x-ndjson",
    )
    logger.info("Uploaded reference: %d records → s3://%s/%s", len(reference_df), BUCKET, REFERENCE_KEY)


def _upload_current(client: boto3.client, severity: str) -> None:
    if severity == "high":
        current_df = generate_prediction_data(
            n_samples=REFERENCE_N,
            class_distribution=HIGH_DRIFT_DISTRIBUTION,
            confidence_mean=HIGH_DRIFT_CONF_MEAN,
            confidence_std=HIGH_DRIFT_CONF_STD,
            seed=7,
        )
    elif severity == "medium":
        current_df = _deterministic_medium_current()
    else:
        raise ValueError(f"Unknown severity: {severity}")

    payload = _to_jsonl(current_df)
    key = f"{date.today().isoformat()}/drift-{severity}-batch.jsonl"
    client.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=io.BytesIO(payload),
        ContentType="application/x-ndjson",
    )
    logger.info("Uploaded current (%s): %d records → s3://%s/%s", severity, len(current_df), BUCKET, key)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--severity", choices=["high", "medium", "none"], required=True)
    parser.add_argument(
        "--skip-reference",
        action="store_true",
        help="Skip re-uploading baseline reference (useful for fast iteration)",
    )
    args = parser.parse_args()

    client = _client()
    _ensure_bucket(client)

    if not args.skip_reference:
        _upload_reference(client)

    _clear_today_prefix(client)

    if args.severity == "none":
        logger.info("Severity=none — today prefix cleared, no current data uploaded")
        return

    _upload_current(client, args.severity)
    logger.info("Done. Monitoring pipeline should now detect %s drift on next run.", args.severity)


if __name__ == "__main__":
    main()
