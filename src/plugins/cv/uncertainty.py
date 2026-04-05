"""Softmax entropy-based uncertainty estimator for CV predictions.

Computes normalized Shannon entropy from softmax probability vectors.
Output range is [0.0, 1.0] where 0 means certain and 1 means
maximally uncertain (uniform distribution).
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


class SoftmaxEntropyEstimator:
    """Measures prediction uncertainty via normalized Shannon entropy.

    Thread-safe: holds no mutable state. All computation is pure-functional
    over the input probability vectors using only the math stdlib module.

    Satisfies the ``UncertaintyEstimator`` protocol defined in
    ``src/core/protocols.py``.
    """

    def estimate(self, predictions: list[list[float]]) -> list[float]:
        """Compute normalized entropy for a batch of softmax predictions.

        Args:
            predictions: List of softmax probability vectors. Each inner list
                sums to 1.0 and contains per-class probabilities.

        Returns:
            Uncertainty scores in [0.0, 1.0], one per prediction.
            0.0 = fully certain, 1.0 = maximally uncertain (uniform).
        """
        return [self._normalized_entropy(p) for p in predictions]

    @staticmethod
    def margin_score(probabilities: list[float]) -> float:
        """Compute margin-based uncertainty: ``1 - (top1 - top2)``.

        A high margin score indicates the model is unsure between the top
        two classes. Useful as a complementary signal to entropy.

        Args:
            probabilities: A single softmax probability vector.

        Returns:
            Margin score in [0.0, 1.0]. 1.0 when the top two classes have
            equal probability; close to 0.0 when the model is very confident.
        """
        if len(probabilities) < 2:
            return 0.0
        sorted_probs = sorted(probabilities, reverse=True)
        return 1.0 - (sorted_probs[0] - sorted_probs[1])

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalized_entropy(probabilities: list[float]) -> float:
        """Compute normalized Shannon entropy for a single probability vector.

        Args:
            probabilities: Softmax probability vector (sums to 1.0).

        Returns:
            Normalized entropy in [0.0, 1.0].
        """
        num_classes = len(probabilities)

        # Edge case: single class — entropy is always 0 (no uncertainty).
        if num_classes <= 1:
            return 0.0

        raw_entropy = 0.0
        for p in probabilities:
            if p > 0.0:
                raw_entropy -= p * math.log(p)

        max_entropy = math.log(num_classes)
        return raw_entropy / max_entropy
