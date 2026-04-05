"""Tests for Protocol interfaces and ValidationReport."""

from __future__ import annotations

from src.core.protocols import (
    DataValidator,
    ModelTrainer,
    SampleSelector,
    UncertaintyEstimator,
    ValidationReport,
)


class TestValidationReport:
    """ValidationReport dataclass behaves correctly."""

    def test_default_values(self):
        report = ValidationReport()
        assert report.total_images == 0
        assert report.issues_found == 0
        assert report.issue_types == {}
        assert report.health_score == 1.0

    def test_to_dict_includes_issue_prefix(self):
        report = ValidationReport(
            total_images=100,
            issues_found=5,
            issue_types={"blurry": 3, "dark": 2},
            health_score=0.95,
        )
        d = report.to_dict()
        assert d["total_images"] == 100
        assert d["issue_blurry"] == 3
        assert d["issue_dark"] == 2


class TestProtocolCompliance:
    """Protocol interfaces have expected methods."""

    def test_data_validator_protocol_has_validate_method(self):
        assert hasattr(DataValidator, "validate")

    def test_model_trainer_protocol_has_train_method(self):
        assert hasattr(ModelTrainer, "train")

    def test_sample_selector_protocol_has_select_method(self):
        assert hasattr(SampleSelector, "select")

    def test_uncertainty_estimator_protocol_has_estimate_method(self):
        assert hasattr(UncertaintyEstimator, "estimate")
