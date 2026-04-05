"""Unit tests for the continuous training flow (Phase B)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestContinuousTrainingFlow:
    """Tests for continuous_training_flow."""

    def _run_flow(self, **overrides):
        """Run the flow with all tasks mocked, applying overrides."""
        from src.core.orchestration.flows.continuous_training_flow import continuous_training_flow

        defaults = {
            "resolve_round_number": 1,
            "integrate_training_data": {
                "total_samples": 100,
                "human_labeled": 50,
                "pseudo_labeled": 50,
                "classes": {"cat": {"train": 40, "val": 10}, "dog": {"train": 40, "val": 10}},
                "output_dir": "data/merged",
            },
            "validate_images": {"health_score": 0.9, "total_images": 100, "issues_found": 10},
            "training_pipeline": {
                "train_loss": 0.2,
                "train_accuracy": 0.92,
                "val_loss": 0.3,
                "val_accuracy": 0.88,
                "best_val_accuracy": 0.90,
            },
            "check_training_quality": {"passed": True, "reason": "All checks passed", "checks": {}},
            "check_champion_gate": {
                "passed": True,
                "reason": "No existing champion",
                "challenger_value": 0.90,
                "champion_value": None,
            },
            "promote_to_champion": {
                "registered_model_name": "cv-classifier",
                "version": "1",
                "run_id": "run-123",
            },
        }
        defaults.update(overrides)

        module = "src.core.orchestration.flows.continuous_training_flow"
        with (
            patch(f"{module}.resolve_round_number", return_value=defaults["resolve_round_number"]),
            patch(f"{module}.integrate_training_data", return_value=defaults["integrate_training_data"]),
            patch(f"{module}.validate_images", return_value=defaults["validate_images"]),
            patch(f"{module}.check_training_quality", return_value=defaults["check_training_quality"]),
            patch(f"{module}.check_champion_gate", return_value=defaults["check_champion_gate"]),
            patch(f"{module}.promote_to_champion", return_value=defaults["promote_to_champion"]),
            patch(f"{module}.create_markdown_artifact"),
            patch(f"{module}._version_data"),
            patch(
                "src.core.orchestration.flows.training_pipeline.training_pipeline",
                return_value=defaults["training_pipeline"],
            ),
        ):
            result = continuous_training_flow.fn(
                trigger_source=overrides.get("trigger_source", "manual"),
            )

        return result

    def test_full_pipeline_success(self) -> None:
        result = self._run_flow()

        assert result["status"] == "completed"
        assert result["round"] == 1
        assert result["trigger_source"] == "manual"
        assert result["training_metrics"]["best_val_accuracy"] == 0.90

    def test_skips_when_no_data(self) -> None:
        result = self._run_flow(
            integrate_training_data={
                "total_samples": 0,
                "human_labeled": 0,
                "pseudo_labeled": 0,
                "classes": {},
            }
        )

        assert result["status"] == "skipped"
        assert "No training data" in result["reason"]

    def test_g1_failure_raises(self) -> None:
        from src.core.orchestration.flows.continuous_training_flow import continuous_training_flow

        module = "src.core.orchestration.flows.continuous_training_flow"
        with (
            patch(f"{module}.resolve_round_number", return_value=1),
            patch(
                f"{module}.integrate_training_data",
                return_value={"total_samples": 100, "human_labeled": 50, "pseudo_labeled": 50},
            ),
            patch(
                f"{module}.validate_images",
                return_value={"health_score": 0.3, "total_images": 100},
            ),
            patch(f"{module}._version_data"),
            patch(f"{module}.create_markdown_artifact"),
            pytest.raises(RuntimeError, match="G1 Data Quality Gate failed"),
        ):
            continuous_training_flow.fn(min_health_score=0.5)

    def test_g2_failure_raises(self) -> None:
        with pytest.raises(RuntimeError, match="G2 Training Quality Gate failed"):
            self._run_flow(
                check_training_quality={
                    "passed": False,
                    "reason": "best_val_accuracy (0.55) < min (0.70)",
                    "checks": {},
                }
            )

    def test_g3_failure_raises(self) -> None:
        with pytest.raises(RuntimeError, match="G3 Champion Gate failed"):
            self._run_flow(
                check_champion_gate={
                    "passed": False,
                    "reason": "Challenger did not exceed champion",
                    "challenger_value": 0.80,
                    "champion_value": 0.85,
                }
            )

    def test_trigger_source_is_recorded(self) -> None:
        result = self._run_flow(trigger_source="drift_detected")
        assert result["trigger_source"] == "drift_detected"

    def test_trigger_source_labeling_complete(self) -> None:
        result = self._run_flow(trigger_source="labeling_complete")
        assert result["trigger_source"] == "labeling_complete"
