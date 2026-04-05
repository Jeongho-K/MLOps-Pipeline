"""Unit tests for Data Accumulation pipeline flow."""

from __future__ import annotations

from unittest.mock import patch


class TestDataAccumulationFlow:
    """Tests for data_accumulation_flow."""

    def test_flow_completes_with_valid_samples(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        samples = [
            {"predicted_class": "cat", "confidence": 0.98, "_s3_key": "accumulated/a.jsonl"},
            {"predicted_class": "dog", "confidence": 0.97, "_s3_key": "accumulated/a.jsonl"},
        ]
        quality_result = {
            "passed": True,
            "reason": "All checks passed",
            "stats": {"num_samples": 2},
        }

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=samples,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.validate_accumulation_quality",
                return_value=quality_result,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.cleanup_accumulated",
                return_value=1,
            ),
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["status"] == "completed"
        assert result["total_samples"] == 2
        assert result["quality_gate_passed"] is True
        assert result["files_cleaned"] == 1

    def test_flow_blocks_on_quality_gate_failure(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        samples = [{"predicted_class": "cat", "confidence": 0.98}] * 10
        quality_result = {
            "passed": False,
            "reason": "Insufficient samples: 10 < 50",
            "stats": {"num_samples": 10},
        }

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=samples,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.validate_accumulation_quality",
                return_value=quality_result,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.cleanup_accumulated",
            ) as mock_cleanup,
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["quality_gate_passed"] is False
        assert "Insufficient samples" in result["reason"]
        mock_cleanup.assert_not_called()

    def test_flow_handles_empty_accumulation(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=[],
            ),
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["status"] == "completed"
        assert result["total_samples"] == 0
        assert result["quality_gate_passed"] is False
        assert result["files_cleaned"] == 0

    def test_flow_skips_cleanup_when_quality_fails(self):
        from src.core.orchestration.flows.data_accumulation_flow import data_accumulation_flow

        samples = [{"predicted_class": "cat", "confidence": 0.95}] * 90 + [
            {"predicted_class": "dog", "confidence": 0.95}
        ] * 10
        quality_result = {
            "passed": False,
            "reason": "Class imbalance: class 'cat' has 90.0% of samples (threshold: 80%)",
            "stats": {
                "num_samples": 100,
                "class_distribution": {"cat": 90, "dog": 10},
                "max_class_ratio": 0.9,
            },
        }

        with (
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.fetch_accumulated_samples",
                return_value=samples,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.validate_accumulation_quality",
                return_value=quality_result,
            ),
            patch(
                "src.core.orchestration.flows.data_accumulation_flow.cleanup_accumulated",
            ) as mock_cleanup,
            patch("src.core.orchestration.flows.data_accumulation_flow.create_markdown_artifact"),
        ):
            result = data_accumulation_flow.fn()

        assert result["quality_gate_passed"] is False
        assert "Class imbalance" in result["reason"]
        assert result["files_cleaned"] == 0
        mock_cleanup.assert_not_called()
