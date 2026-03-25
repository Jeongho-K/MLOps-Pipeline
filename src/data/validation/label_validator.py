"""Label validation using CleanLab.

Detects likely mislabeled samples and computes per-sample label quality scores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from cleanlab.filter import find_label_issues
from cleanlab.rank import get_label_quality_scores

logger = logging.getLogger(__name__)


@dataclass
class LabelReport:
    """Summary of label validation results."""

    total_samples: int = 0
    issues_found: int = 0
    issue_indices: list[int] = field(default_factory=list)
    avg_label_quality: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for MLflow logging."""
        return {
            "total_samples": self.total_samples,
            "label_issues_found": self.issues_found,
            "label_issue_rate": self.issues_found / max(self.total_samples, 1),
            "avg_label_quality": self.avg_label_quality,
        }


def validate_labels(
    labels: np.ndarray,
    pred_probs: np.ndarray,
    filter_by: str = "prune_by_noise_rate",
) -> LabelReport:
    """Find label issues using CleanLab confident learning.

    Args:
        labels: Array of integer labels (shape: [N]).
        pred_probs: Model's predicted probabilities (shape: [N, num_classes]).
            Typically from cross-validation or a held-out model.
        filter_by: Method for filtering label issues.
            Options: "prune_by_class", "prune_by_noise_rate", "both",
            "confident_learning", "predicted_neq_given".

    Returns:
        LabelReport with issue indices and quality scores.
    """
    if len(labels) == 0:
        raise ValueError("Cannot validate empty label set.")

    if labels.shape[0] != pred_probs.shape[0]:
        raise ValueError(
            f"Labels ({labels.shape[0]}) and pred_probs ({pred_probs.shape[0]}) "
            "must have the same number of samples."
        )

    if pred_probs.ndim != 2:
        raise ValueError(f"pred_probs must be 2D, got shape {pred_probs.shape}.")

    if np.any(pred_probs < 0) or np.any(pred_probs > 1):
        raise ValueError("pred_probs values must be in [0, 1]. Got unnormalized values.")

    logger.info("Starting CleanLab label validation on %d samples", len(labels))

    try:
        issue_mask = find_label_issues(
            labels=labels,
            pred_probs=pred_probs,
            filter_by=filter_by,
        )
        issue_indices = np.where(issue_mask)[0].tolist()

        quality_scores = get_label_quality_scores(
            labels=labels,
            pred_probs=pred_probs,
        )
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as e:
        raise RuntimeError(f"CleanLab analysis failed: {e}") from e

    report = LabelReport(
        total_samples=len(labels),
        issues_found=len(issue_indices),
        issue_indices=issue_indices,
        avg_label_quality=float(np.mean(quality_scores)),
    )

    logger.info(
        "Label validation complete: %d/%d issues (%.1f%%), avg quality=%.3f",
        report.issues_found,
        report.total_samples,
        100 * report.issues_found / max(report.total_samples, 1),
        report.avg_label_quality,
    )

    return report
