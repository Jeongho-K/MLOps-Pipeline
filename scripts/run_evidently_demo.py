"""Evidently drift detection demo.

Generates reference and current prediction data, runs drift detection,
creates HTML reports, and pushes metrics to Prometheus Pushgateway.

Usage:
    python scripts/run_evidently_demo.py
"""

from __future__ import annotations

import json
import logging
import tempfile
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.monitoring.evidently.drift_detector import (
    detect_drift,
    push_drift_metrics,
    check_drift_threshold,
    save_drift_report_html,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CLASSES = ["airplane", "automobile", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck"]
PUSHGATEWAY_URL = "http://localhost:9091"


def generate_prediction_data(
    n_samples: int,
    class_distribution: list[float] | None = None,
    confidence_mean: float = 0.85,
    confidence_std: float = 0.1,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic prediction log data.

    Args:
        n_samples: Number of prediction records.
        class_distribution: Probability of each class (uniform if None).
        confidence_mean: Mean confidence score.
        confidence_std: Std of confidence.
        seed: Random seed.

    Returns:
        DataFrame with predicted_class and confidence columns.
    """
    rng = np.random.RandomState(seed)

    if class_distribution is None:
        class_distribution = [1.0 / len(CLASSES)] * len(CLASSES)

    predicted_classes = rng.choice(len(CLASSES), size=n_samples, p=class_distribution)
    confidences = np.clip(rng.normal(confidence_mean, confidence_std, n_samples), 0.1, 1.0)

    return pd.DataFrame({
        "predicted_class": predicted_classes,
        "confidence": confidences,
    })


def main() -> None:
    """Run Evidently demo with reference vs drifted data."""
    output_dir = Path("demo-screenshots")
    output_dir.mkdir(exist_ok=True)

    # 1. Generate reference data (balanced classes, high confidence)
    logger.info("Generating reference data (balanced, high confidence)...")
    reference = generate_prediction_data(
        n_samples=500,
        confidence_mean=0.88,
        confidence_std=0.08,
        seed=42,
    )

    # 2. Generate current data WITH drift (skewed classes, lower confidence)
    logger.info("Generating current data (drifted: skewed classes, lower confidence)...")
    drifted_distribution = [0.25, 0.25, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.10, 0.10]
    current = generate_prediction_data(
        n_samples=500,
        class_distribution=drifted_distribution,
        confidence_mean=0.72,
        confidence_std=0.15,
        seed=99,
    )

    # 3. Run drift detection
    logger.info("Running Evidently drift detection...")
    drift_result = detect_drift(reference, current)
    logger.info("Drift result: %s", drift_result)

    # 4. Run TestSuite quality gate
    logger.info("Running Evidently TestSuite quality gate...")
    test_result = check_drift_threshold(reference, current, drift_share_threshold=0.3)
    logger.info("TestSuite result: passed=%s, drift_score=%.4f", test_result["passed"], test_result["drift_score"])

    # 5. Save HTML drift report
    report_path = str(output_dir / "evidently-drift-report.html")
    save_drift_report_html(reference, current, report_path)
    logger.info("Drift report saved to %s", report_path)

    # 6. Push metrics to Prometheus Pushgateway
    try:
        push_drift_metrics(PUSHGATEWAY_URL, drift_result["drift_detected"], drift_result["drift_score"])
        logger.info("Metrics pushed to Pushgateway at %s", PUSHGATEWAY_URL)
    except Exception as e:
        logger.warning("Failed to push to Pushgateway: %s", e)

    # 7. Log summary
    logger.info("\n" + "=" * 60)
    logger.info("EVIDENTLY DRIFT DETECTION SUMMARY")
    logger.info("=" * 60)
    logger.info("Reference data:  %d samples", len(reference))
    logger.info("Current data:    %d samples", len(current))
    logger.info("Drift detected:  %s", drift_result["drift_detected"])
    logger.info("Drift score:     %.4f", drift_result["drift_score"])
    logger.info("Column drifts:   %s", drift_result["column_drifts"])
    logger.info("TestSuite pass:  %s", test_result["passed"])
    logger.info("Report:          %s", report_path)
    logger.info("=" * 60)

    # 8. Open report in browser
    webbrowser.open(f"file://{Path(report_path).resolve()}")


if __name__ == "__main__":
    main()
