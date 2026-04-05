"""Unit tests for ConfidenceRouter."""

import pytest

from src.core.active_learning.routing.confidence_router import ConfidenceRouter, RoutingDecision


class TestRoutingDecision:
    def test_creation_and_field_access(self):
        decision = RoutingDecision(route="auto_accumulate", confidence=0.99, uncertainty=0.01)
        assert decision.route == "auto_accumulate"
        assert decision.confidence == 0.99
        assert decision.uncertainty == 0.01

    def test_frozen(self):
        decision = RoutingDecision(route="discard", confidence=0.5, uncertainty=0.3)
        with pytest.raises(AttributeError):
            decision.route = "human_review"  # type: ignore[misc]


class TestConfidenceRouter:
    def test_high_confidence_routes_to_auto_accumulate(self):
        router = ConfidenceRouter()
        result = router.route(confidence=0.98, uncertainty=0.02)
        assert result.route == "auto_accumulate"
        assert result.confidence == 0.98
        assert result.uncertainty == 0.02

    def test_high_uncertainty_routes_to_human_review(self):
        router = ConfidenceRouter()
        result = router.route(confidence=0.4, uncertainty=0.7)
        assert result.route == "human_review"

    def test_middle_ground_routes_to_discard(self):
        router = ConfidenceRouter()
        result = router.route(confidence=0.7, uncertainty=0.3)
        assert result.route == "discard"

    def test_auto_accumulate_priority_over_human_review(self):
        """Even with high uncertainty, high confidence wins."""
        router = ConfidenceRouter()
        result = router.route(confidence=0.96, uncertainty=0.8)
        assert result.route == "auto_accumulate"

    def test_boundary_auto_threshold(self):
        """Confidence exactly at threshold routes to auto_accumulate."""
        router = ConfidenceRouter()
        result = router.route(confidence=0.95, uncertainty=0.0)
        assert result.route == "auto_accumulate"

    def test_boundary_uncertainty_threshold(self):
        """Uncertainty exactly at threshold routes to human_review."""
        router = ConfidenceRouter()
        result = router.route(confidence=0.5, uncertainty=0.5)
        assert result.route == "human_review"

    def test_custom_thresholds(self):
        router = ConfidenceRouter(auto_threshold=0.8, uncertainty_threshold=0.3)
        # Would be discard with defaults, but auto_accumulate with lowered threshold
        assert router.route(confidence=0.85, uncertainty=0.1).route == "auto_accumulate"
        # Would be discard with defaults, but human_review with lowered threshold
        assert router.route(confidence=0.5, uncertainty=0.35).route == "human_review"

    def test_route_batch(self):
        router = ConfidenceRouter()
        results = router.route_batch(
            confidences=[0.98, 0.4, 0.7],
            uncertainties=[0.02, 0.7, 0.3],
        )
        assert len(results) == 3
        assert results[0].route == "auto_accumulate"
        assert results[1].route == "human_review"
        assert results[2].route == "discard"

    def test_route_batch_length_mismatch_raises(self):
        router = ConfidenceRouter()
        with pytest.raises(ValueError, match="Length mismatch"):
            router.route_batch(confidences=[0.9, 0.8], uncertainties=[0.1])

    def test_route_batch_empty(self):
        router = ConfidenceRouter()
        results = router.route_batch(confidences=[], uncertainties=[])
        assert results == []
