"""Unit tests for SoftmaxEntropyEstimator."""

from __future__ import annotations

import pytest

from src.plugins.cv.uncertainty import SoftmaxEntropyEstimator


class TestSoftmaxEntropyEstimator:
    """Tests for the estimate() method."""

    def setup_method(self):
        self.estimator = SoftmaxEntropyEstimator()

    def test_certain_prediction_returns_zero(self):
        """A one-hot prediction should have zero entropy."""
        result = self.estimator.estimate([[1.0, 0.0, 0.0]])
        assert result == [pytest.approx(0.0)]

    def test_uniform_distribution_returns_one(self):
        """A uniform distribution should have maximum entropy (1.0)."""
        result = self.estimator.estimate([[0.25, 0.25, 0.25, 0.25]])
        assert result == [pytest.approx(1.0)]

    def test_two_class_entropy(self):
        """Equal probability across two classes should yield entropy 1.0."""
        result = self.estimator.estimate([[0.5, 0.5]])
        assert result == [pytest.approx(1.0)]

    def test_batch_predictions(self):
        """Multiple predictions should return one score per prediction."""
        preds = [
            [1.0, 0.0, 0.0],
            [0.5, 0.5, 0.0],
            [1 / 3, 1 / 3, 1 / 3],
        ]
        result = self.estimator.estimate(preds)
        assert len(result) == 3
        assert result[0] == pytest.approx(0.0)
        assert result[2] == pytest.approx(1.0)
        # Middle case: partially uncertain, between 0 and 1
        assert 0.0 < result[1] < 1.0

    def test_near_zero_probabilities(self):
        """Small but nonzero probabilities should be handled without error."""
        result = self.estimator.estimate([[0.99, 0.005, 0.005]])
        assert len(result) == 1
        assert 0.0 < result[0] < 0.5  # Low entropy, but not zero

    def test_single_class(self):
        """A single-class vector should return 0.0 (no uncertainty possible)."""
        result = self.estimator.estimate([[1.0]])
        assert result == [pytest.approx(0.0)]

    def test_empty_predictions(self):
        """An empty prediction list should return an empty list."""
        result = self.estimator.estimate([])
        assert result == []

    def test_output_range(self):
        """All outputs should fall within [0.0, 1.0]."""
        preds = [
            [1.0, 0.0, 0.0],
            [0.5, 0.5, 0.0],
            [1 / 3, 1 / 3, 1 / 3],
            [0.9, 0.05, 0.05],
            [0.25, 0.25, 0.25, 0.25],
            [0.7, 0.2, 0.1],
        ]
        result = self.estimator.estimate(preds)
        for score in result:
            assert 0.0 <= score <= 1.0

    def test_monotonicity_more_uniform_means_higher_entropy(self):
        """More uniform distributions should produce higher entropy."""
        preds = [
            [0.9, 0.05, 0.05],
            [0.6, 0.2, 0.2],
            [1 / 3, 1 / 3, 1 / 3],
        ]
        result = self.estimator.estimate(preds)
        assert result[0] < result[1] < result[2]


class TestMarginScore:
    """Tests for the margin_score() static method."""

    def test_certain_prediction(self):
        """Large gap between top-1 and top-2 yields a low margin score."""
        score = SoftmaxEntropyEstimator.margin_score([0.9, 0.05, 0.05])
        assert score == pytest.approx(0.15)

    def test_uniform_prediction(self):
        """Uniform distribution yields margin score of 1.0."""
        score = SoftmaxEntropyEstimator.margin_score([0.25, 0.25, 0.25, 0.25])
        assert score == pytest.approx(1.0)

    def test_two_class(self):
        """Equal two-class probabilities yield margin score of 1.0."""
        score = SoftmaxEntropyEstimator.margin_score([0.5, 0.5])
        assert score == pytest.approx(1.0)

    def test_single_class_returns_zero(self):
        """A single-class vector has no meaningful margin; returns 0.0."""
        score = SoftmaxEntropyEstimator.margin_score([1.0])
        assert score == pytest.approx(0.0)

    def test_empty_returns_zero(self):
        """An empty vector returns 0.0."""
        score = SoftmaxEntropyEstimator.margin_score([])
        assert score == pytest.approx(0.0)

    def test_unsorted_input(self):
        """Margin score should work regardless of input ordering."""
        score = SoftmaxEntropyEstimator.margin_score([0.05, 0.9, 0.05])
        assert score == pytest.approx(0.15)
