"""Unit tests for data validation modules."""

import numpy as np
import pytest

from src.plugins.cv.label_validator import LabelReport, validate_labels


class TestLabelValidator:
    """Tests for label validation using CleanLab."""

    def test_validate_labels_no_issues(self) -> None:
        """Clean labels should produce zero issues."""
        np.random.seed(42)
        n_samples = 100
        n_classes = 3

        labels = np.random.randint(0, n_classes, size=n_samples)
        pred_probs = np.zeros((n_samples, n_classes))
        for i, label in enumerate(labels):
            pred_probs[i, label] = 0.9
            remaining = 0.1 / (n_classes - 1)
            for j in range(n_classes):
                if j != label:
                    pred_probs[i, j] = remaining

        report = validate_labels(labels, pred_probs)

        assert isinstance(report, LabelReport)
        assert report.total_samples == n_samples
        assert report.issues_found == 0
        assert report.avg_label_quality > 0.8

    def test_validate_labels_with_noise(self) -> None:
        """Noisy labels should be detected."""
        np.random.seed(42)
        n_samples = 200
        n_classes = 3

        labels = np.random.randint(0, n_classes, size=n_samples)
        pred_probs = np.zeros((n_samples, n_classes))
        for i, label in enumerate(labels):
            pred_probs[i, label] = 0.9
            remaining = 0.1 / (n_classes - 1)
            for j in range(n_classes):
                if j != label:
                    pred_probs[i, j] = remaining

        # Flip 20% of labels
        flip_indices = np.random.choice(n_samples, size=40, replace=False)
        for idx in flip_indices:
            labels[idx] = (labels[idx] + 1) % n_classes

        report = validate_labels(labels, pred_probs)

        assert report.issues_found > 0
        assert len(report.issue_indices) > 0

    def test_validate_labels_mismatched_shapes(self) -> None:
        """Mismatched shapes should raise ValueError."""
        labels = np.array([0, 1, 2])
        pred_probs = np.array([[0.9, 0.1], [0.1, 0.9]])

        with pytest.raises(ValueError, match="same number of samples"):
            validate_labels(labels, pred_probs)

    def test_label_report_to_dict(self) -> None:
        """Report should serialize to a dict."""
        report = LabelReport(
            total_samples=100,
            issues_found=5,
            issue_indices=[1, 3, 7, 12, 45],
            avg_label_quality=0.92,
        )

        d = report.to_dict()
        assert d["total_samples"] == 100
        assert d["label_issues_found"] == 5
        assert d["label_issue_rate"] == pytest.approx(0.05)
        assert d["avg_label_quality"] == pytest.approx(0.92)
