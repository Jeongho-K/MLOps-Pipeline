"""Confidence-based routing for prediction triage.

Routes predictions into three paths based on confidence and uncertainty scores:
- auto_accumulate: high confidence predictions become pseudo-labels
- human_review: uncertain predictions go to Label Studio for human labeling
- discard: middle-ground predictions are logged only
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Result of routing a single prediction.

    Attributes:
        route: The assigned routing path.
        confidence: The model's confidence score for the prediction.
        uncertainty: The estimated uncertainty of the prediction.
    """

    route: Literal["auto_accumulate", "human_review", "discard"]
    confidence: float
    uncertainty: float


class ConfidenceRouter:
    """Routes predictions based on confidence and uncertainty thresholds.

    The routing logic applies the following priority:
        1. confidence >= auto_threshold -> auto_accumulate (pseudo-label)
        2. uncertainty >= uncertainty_threshold -> human_review (Label Studio)
        3. otherwise -> discard (logged only)

    Auto-accumulate takes priority: even if uncertainty is high, a very high
    confidence score results in pseudo-labeling.

    Args:
        auto_threshold: Minimum confidence for auto-accumulation. Defaults to 0.95.
        uncertainty_threshold: Minimum uncertainty for human review. Defaults to 0.5.
    """

    def __init__(self, auto_threshold: float = 0.95, uncertainty_threshold: float = 0.5) -> None:
        self._auto_threshold = auto_threshold
        self._uncertainty_threshold = uncertainty_threshold

    def route(self, confidence: float, uncertainty: float) -> RoutingDecision:
        """Route a single prediction based on its confidence and uncertainty.

        Args:
            confidence: Model confidence score, typically in [0, 1].
            uncertainty: Estimated uncertainty score, typically in [0, 1].

        Returns:
            A RoutingDecision with the assigned route and input scores.
        """
        if confidence >= self._auto_threshold:
            route: Literal["auto_accumulate", "human_review", "discard"] = "auto_accumulate"
        elif uncertainty >= self._uncertainty_threshold:
            route = "human_review"
        else:
            route = "discard"

        logger.debug("Routed prediction (conf=%.4f, unc=%.4f) -> %s", confidence, uncertainty, route)
        return RoutingDecision(route=route, confidence=confidence, uncertainty=uncertainty)

    def route_batch(self, confidences: list[float], uncertainties: list[float]) -> list[RoutingDecision]:
        """Route a batch of predictions.

        Args:
            confidences: List of confidence scores.
            uncertainties: List of uncertainty scores.

        Returns:
            List of RoutingDecision objects, one per input pair.

        Raises:
            ValueError: If the input lists have different lengths.
        """
        if len(confidences) != len(uncertainties):
            raise ValueError(
                f"Length mismatch: confidences ({len(confidences)}) != uncertainties ({len(uncertainties)})"
            )

        return [self.route(c, u) for c, u in zip(confidences, uncertainties, strict=True)]
