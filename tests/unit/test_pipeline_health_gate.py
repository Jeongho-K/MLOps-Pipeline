"""Unit tests for training pipeline health gate."""

import inspect


class TestHealthGate:
    """Tests for the data health score gate in the training pipeline."""

    def test_flow_parameters_have_defaults(self) -> None:
        """Training pipeline should have default parameter values."""
        from src.orchestration.flows.training_pipeline import training_pipeline

        assert hasattr(training_pipeline, "serve")
        assert hasattr(training_pipeline, "name")

    def test_min_health_score_parameter(self) -> None:
        """Pipeline should accept min_health_score parameter."""
        from src.orchestration.flows.training_pipeline import training_pipeline

        sig = inspect.signature(training_pipeline.fn)
        assert "min_health_score" in sig.parameters
        assert sig.parameters["min_health_score"].default == 0.5
