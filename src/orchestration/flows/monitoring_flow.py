"""Daily drift monitoring pipeline flow.

Orchestrates: fetch prediction logs → fetch reference data →
run drift detection → upload drift report.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, timedelta
from typing import Any

import boto3
import pandas as pd
from prefect import flow, task

from src.monitoring.evidently.config import DriftConfig
from src.monitoring.evidently.drift_detector import (
    build_dataframe_from_logs,
    detect_drift,
    push_drift_metrics,
    save_drift_report_html,
)

logger = logging.getLogger(__name__)


@task(name="fetch-prediction-logs", retries=2, retry_delay_seconds=30)
def fetch_prediction_logs(
    s3_endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    lookback_days: int = 1,
) -> pd.DataFrame:
    """Fetch prediction logs from S3 for each day in the lookback window.

    Lists objects under ``{YYYY-MM-DD}/`` prefixes for each day in the
    lookback window, concatenates all JSONL file contents, and returns
    a single DataFrame.

    Args:
        s3_endpoint: S3-compatible endpoint URL (e.g. ``http://minio:9000``).
        bucket: S3 bucket name containing prediction logs.
        access_key: AWS/MinIO access key ID.
        secret_key: AWS/MinIO secret access key.
        lookback_days: Number of past days to fetch logs for.

    Returns:
        DataFrame constructed from all fetched JSONL records.
        Returns an empty DataFrame if no logs are found.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    today = date.today()
    all_jsonl: list[str] = []

    for offset in range(lookback_days):
        day = today - timedelta(days=offset)
        prefix = f"{day.isoformat()}/"

        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objects = response.get("Contents", [])

        for obj in objects:
            key = obj["Key"]
            if not key.endswith(".jsonl"):
                continue
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            all_jsonl.append(body.decode("utf-8"))

    if not all_jsonl:
        logger.info("No prediction logs found for the last %d day(s).", lookback_days)
        return pd.DataFrame()

    combined = "\n".join(all_jsonl)
    df = build_dataframe_from_logs(combined)
    logger.info("Fetched %d prediction log records.", len(df))
    return df


@task(name="fetch-reference-data", retries=2, retry_delay_seconds=30)
def fetch_reference_data(
    s3_endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    reference_path: str,
) -> pd.DataFrame:
    """Fetch the reference (baseline) dataset from S3.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        bucket: S3 bucket name containing the reference data.
        access_key: AWS/MinIO access key ID.
        secret_key: AWS/MinIO secret access key.
        reference_path: S3 object key for the reference JSONL file.

    Returns:
        DataFrame constructed from the reference JSONL file.
        Returns an empty DataFrame if the file is empty.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    body = client.get_object(Bucket=bucket, Key=reference_path)["Body"].read()
    raw_jsonl = body.decode("utf-8")
    df = build_dataframe_from_logs(raw_jsonl)
    logger.info("Fetched %d reference records from s3://%s/%s.", len(df), bucket, reference_path)
    return df


@task(name="run-drift-detection")
def run_drift_detection(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    pushgateway_url: str,
) -> dict[str, Any]:
    """Run Evidently drift detection and push results to Prometheus Pushgateway.

    Args:
        reference: Reference (baseline) DataFrame.
        current: Current (production) DataFrame.
        pushgateway_url: URL of the Prometheus Pushgateway.

    Returns:
        Dictionary with keys ``drift_detected`` (bool), ``drift_score`` (float),
        and ``column_drifts`` (dict[str, float]).
    """
    result = detect_drift(reference, current)
    push_drift_metrics(
        pushgateway_url=pushgateway_url,
        drift_detected=result["drift_detected"],
        drift_score=result["drift_score"],
    )
    logger.info(
        "Drift detection complete: drift_detected=%s drift_score=%.4f",
        result["drift_detected"],
        result["drift_score"],
    )
    return result


@task(name="upload-drift-report", retries=2, retry_delay_seconds=30)
def upload_drift_report(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    s3_endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
) -> str:
    """Generate an HTML drift report and upload it to S3.

    Writes the report to a temporary file, uploads it to S3 under
    ``{YYYY-MM-DD}/drift-report.html``, and returns the S3 key.

    Args:
        reference: Reference (baseline) DataFrame.
        current: Current (production) DataFrame.
        s3_endpoint: S3-compatible endpoint URL.
        bucket: S3 bucket name for drift reports.
        access_key: AWS/MinIO access key ID.
        secret_key: AWS/MinIO secret access key.

    Returns:
        S3 object key of the uploaded report.
    """
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    today = date.today()
    s3_key = f"{today.isoformat()}/drift-report.html"

    fd, tmp_path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        save_drift_report_html(reference, current, tmp_path)
        client.upload_file(tmp_path, bucket, s3_key)
        logger.info("Drift report uploaded to s3://%s/%s", bucket, s3_key)
    finally:
        os.unlink(tmp_path)
    return s3_key


@flow(
    name="monitoring-pipeline",
    retries=0,
    description="Daily drift monitoring: fetch logs → detect drift → upload report",
)
def monitoring_pipeline(
    s3_endpoint: str | None = None,
    s3_access_key: str | None = None,
    s3_secret_key: str | None = None,
    prediction_logs_bucket: str | None = None,
    drift_reports_bucket: str | None = None,
    reference_path: str | None = None,
    lookback_days: int | None = None,
    pushgateway_url: str | None = None,
) -> dict[str, Any]:
    """Run the full drift monitoring pipeline.

    All parameters default to values from DriftConfig (DRIFT_ env prefix).

    Steps:
        1. Fetch prediction logs from S3 for the lookback window.
        2. Fetch reference (baseline) data from S3.
        3. Filter both DataFrames to common columns.
        4. Run Evidently drift detection and push metrics to Pushgateway.
        5. Generate and upload an HTML drift report to S3.

    Args:
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: AWS/MinIO access key ID.
        s3_secret_key: AWS/MinIO secret access key.
        prediction_logs_bucket: Bucket containing prediction logs.
        drift_reports_bucket: Bucket for storing drift reports.
        reference_path: S3 key of the reference JSONL file.
        lookback_days: Number of past days to include in current data.
        pushgateway_url: URL of the Prometheus Pushgateway.

    Returns:
        Dictionary with drift detection results and the uploaded report S3 key.
        Returns ``{"status": "skipped", "reason": ...}`` if data is insufficient.
    """
    cfg = DriftConfig()
    s3_endpoint = s3_endpoint or cfg.s3_endpoint
    s3_access_key = s3_access_key or cfg.s3_access_key
    s3_secret_key = s3_secret_key or cfg.s3_secret_key
    prediction_logs_bucket = prediction_logs_bucket or cfg.prediction_logs_bucket
    drift_reports_bucket = drift_reports_bucket or cfg.drift_reports_bucket
    reference_path = reference_path or cfg.reference_path
    lookback_days = lookback_days or cfg.lookback_days
    pushgateway_url = pushgateway_url or cfg.pushgateway_url

    # Step 1: Fetch prediction logs
    current_df = fetch_prediction_logs(
        s3_endpoint=s3_endpoint,
        bucket=prediction_logs_bucket,
        access_key=s3_access_key,
        secret_key=s3_secret_key,
        lookback_days=lookback_days,
    )
    if current_df.empty:
        logger.warning("No prediction logs found; skipping monitoring pipeline.")
        return {"status": "skipped", "reason": "no prediction logs"}

    # Step 2: Fetch reference data
    reference_df = fetch_reference_data(
        s3_endpoint=s3_endpoint,
        bucket=prediction_logs_bucket,
        access_key=s3_access_key,
        secret_key=s3_secret_key,
        reference_path=reference_path,
    )
    if reference_df.empty:
        logger.warning("Reference data is empty; skipping monitoring pipeline.")
        return {"status": "skipped", "reason": "empty reference data"}

    # Step 3: Filter to common columns
    common_cols = ["predicted_class", "confidence"]
    current_cols = [c for c in common_cols if c in current_df.columns]
    reference_cols = [c for c in common_cols if c in reference_df.columns]
    shared_cols = [c for c in current_cols if c in reference_cols]

    if not shared_cols:
        logger.warning(
            "No shared columns (%s) between reference and current data; skipping.",
            common_cols,
        )
        return {"status": "skipped", "reason": "no shared columns"}

    current_filtered = current_df[shared_cols]
    reference_filtered = reference_df[shared_cols]

    # Step 4: Run drift detection
    drift_result = run_drift_detection(
        reference=reference_filtered,
        current=current_filtered,
        pushgateway_url=pushgateway_url,
    )

    # Step 5: Upload drift report
    report_key = upload_drift_report(
        reference=reference_filtered,
        current=current_filtered,
        s3_endpoint=s3_endpoint,
        bucket=drift_reports_bucket,
        access_key=s3_access_key,
        secret_key=s3_secret_key,
    )

    result: dict[str, Any] = {
        **drift_result,
        "report_s3_key": report_key,
        "status": "completed",
    }
    logger.info("Monitoring pipeline complete: %s", result)
    return result
