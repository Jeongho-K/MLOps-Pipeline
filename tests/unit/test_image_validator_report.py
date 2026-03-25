"""Unit tests for image validator report and error handling."""

import pytest

from src.data.validation.image_validator import ValidationReport


class TestValidationReport:
    """Tests for ValidationReport dataclass."""

    def test_to_dict_basic(self) -> None:
        """Report should serialize correctly."""
        report = ValidationReport(
            total_images=100,
            issues_found=5,
            issue_types={"blurry": 3, "dark": 2},
            health_score=0.95,
        )

        d = report.to_dict()
        assert d["total_images"] == 100
        assert d["issues_found"] == 5
        assert d["health_score"] == pytest.approx(0.95)
        assert d["issue_blurry"] == 3
        assert d["issue_dark"] == 2

    def test_to_dict_empty_issues(self) -> None:
        """Report with no issues should serialize cleanly."""
        report = ValidationReport(
            total_images=50,
            issues_found=0,
            issue_types={},
            health_score=1.0,
        )

        d = report.to_dict()
        assert d["total_images"] == 50
        assert d["issues_found"] == 0
        assert d["health_score"] == pytest.approx(1.0)

    def test_validate_nonexistent_path(self) -> None:
        """Non-existent path should raise FileNotFoundError."""
        from src.data.validation.image_validator import validate_image_dataset

        with pytest.raises(FileNotFoundError, match="does not exist"):
            validate_image_dataset("/nonexistent/path")
