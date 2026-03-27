"""Evidently-based drift detection for monitoring prediction distributions."""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

logger = logging.getLogger(__name__)


def build_dataframe_from_logs(raw_jsonl: str) -> pd.DataFrame:
    """Parse a JSONL string into a DataFrame.

    Args:
        raw_jsonl: Newline-delimited JSON string where each line is a JSON object.

    Returns:
        DataFrame constructed from the parsed JSON records.
        Returns an empty DataFrame if the input is empty or blank.
    """
    if not raw_jsonl or not raw_jsonl.strip():
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for line in raw_jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


def detect_drift(reference: pd.DataFrame, current: pd.DataFrame) -> dict[str, Any]:
    """Run Evidently DataDriftPreset and return a summary dict.

    Args:
        reference: Reference (baseline) DataFrame.
        current: Current (production) DataFrame to compare against the reference.

    Returns:
        Dictionary with the following keys:
            - drift_detected (bool): Whether dataset-level drift was detected.
            - drift_score (float): Share of drifted columns (0.0–1.0).
            - column_drifts (dict[str, float]): Per-column p-values or drift scores.
    """
    report = Report([DataDriftPreset()])
    result = report.run(reference_data=reference, current_data=current)
    metrics = result.dict()["metrics"]

    drift_detected: bool = False
    drift_score: float = 0.0
    column_drifts: dict[str, float] = {}

    for metric in metrics:
        metric_name: str = metric["metric_name"]
        value = metric["value"]

        if "DriftedColumnsCount" in metric_name:
            drift_share_threshold: float = metric["config"]["drift_share"]
            share: float = float(value["share"])
            drift_score = share
            drift_detected = share >= drift_share_threshold
        elif "ValueDrift" in metric_name:
            column: str = metric["config"]["column"]
            column_drifts[column] = float(value)

    logger.info(
        "Drift detection complete: drift_detected=%s drift_score=%.4f columns_checked=%d",
        drift_detected,
        drift_score,
        len(column_drifts),
    )

    return {
        "drift_detected": drift_detected,
        "drift_score": drift_score,
        "column_drifts": column_drifts,
    }


def save_drift_report_html(reference: pd.DataFrame, current: pd.DataFrame, output_path: str) -> None:
    """Run drift analysis and save the HTML report to a file.

    Args:
        reference: Reference (baseline) DataFrame.
        current: Current (production) DataFrame to compare against the reference.
        output_path: Local filesystem path where the HTML report will be written.
    """
    report = Report([DataDriftPreset()])
    result = report.run(reference_data=reference, current_data=current)
    result.save_html(output_path)
    logger.info("Drift report saved to %s", output_path)


def push_drift_metrics(pushgateway_url: str, drift_detected: bool, drift_score: float) -> None:
    """Push drift metrics to a Prometheus Pushgateway.

    Creates an isolated CollectorRegistry to avoid conflicts with the default
    global registry. Pushes two gauges:
        - evidently_drift_detected: 1.0 if drift was detected, else 0.0
        - evidently_drift_score: Share of drifted columns (0.0–1.0)

    Args:
        pushgateway_url: URL of the Prometheus Pushgateway (e.g. ``http://pushgateway:9091``).
        drift_detected: Whether dataset-level drift was detected.
        drift_score: Share of drifted columns (0.0–1.0).
    """
    registry = CollectorRegistry()

    g_detected = Gauge(
        "evidently_drift_detected",
        "1 if dataset drift was detected, else 0",
        registry=registry,
    )
    g_score = Gauge(
        "evidently_drift_score",
        "Share of drifted columns (0.0 to 1.0)",
        registry=registry,
    )

    g_detected.set(1.0 if drift_detected else 0.0)
    g_score.set(drift_score)

    push_to_gateway(pushgateway_url, job="evidently_drift", registry=registry)
    logger.info(
        "Pushed drift metrics to Pushgateway: drift_detected=%s drift_score=%.4f",
        drift_detected,
        drift_score,
    )
