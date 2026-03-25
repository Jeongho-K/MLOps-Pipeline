"""Unit tests for training pipeline health gate behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestHealthGate:
    """Tests for the data health score gate in the training pipeline."""

    def test_low_health_score_blocks_training(self) -> None:
        """Health score below threshold should raise RuntimeError."""
        from src.orchestration.flows.training_pipeline import training_pipeline

        with (
            patch("src.orchestration.flows.training_pipeline.prepare_dataset") as mock_prepare,
            patch("src.orchestration.flows.training_pipeline.validate_images") as mock_validate,
            patch("src.orchestration.flows.training_pipeline.train_model") as mock_train,
        ):
            mock_prepare.return_value = Path("/tmp/data")
            mock_validate.return_value = {"health_score": 0.3, "total_images": 100, "issues_found": 70}

            with pytest.raises(RuntimeError, match="health score"):
                training_pipeline.fn(
                    data_dir="/tmp/data",
                    min_health_score=0.5,
                )

            mock_train.assert_not_called()

    def test_high_health_score_allows_training(self) -> None:
        """Health score above threshold should proceed to training."""
        from src.orchestration.flows.training_pipeline import training_pipeline

        with (
            patch("src.orchestration.flows.training_pipeline.prepare_dataset") as mock_prepare,
            patch("src.orchestration.flows.training_pipeline.validate_images") as mock_validate,
            patch("src.orchestration.flows.training_pipeline.train_model") as mock_train,
        ):
            mock_prepare.return_value = Path("/tmp/data")
            mock_validate.return_value = {"health_score": 0.9, "total_images": 100, "issues_found": 10}
            mock_train.return_value = {"val_loss": 0.5, "val_accuracy": 0.8, "best_val_accuracy": 0.85}

            result = training_pipeline.fn(
                data_dir="/tmp/data",
                min_health_score=0.5,
            )

            mock_train.assert_called_once()
            assert result["best_val_accuracy"] == 0.85

    def test_missing_health_score_key_raises(self) -> None:
        """Missing health_score key should raise RuntimeError."""
        from src.orchestration.flows.training_pipeline import training_pipeline

        with (
            patch("src.orchestration.flows.training_pipeline.prepare_dataset") as mock_prepare,
            patch("src.orchestration.flows.training_pipeline.validate_images") as mock_validate,
        ):
            mock_prepare.return_value = Path("/tmp/data")
            mock_validate.return_value = {"total_images": 100}  # no health_score

            with pytest.raises(RuntimeError, match="missing 'health_score'"):
                training_pipeline.fn(data_dir="/tmp/data")

    def test_partial_split_train_only_raises(self, tmp_path: Path) -> None:
        """Only train/ without val/ should raise FileNotFoundError."""
        from src.orchestration.tasks.data_tasks import prepare_dataset

        (tmp_path / "train").mkdir()
        with pytest.raises(FileNotFoundError, match="train.*val"):
            prepare_dataset.fn(str(tmp_path))

    def test_partial_split_val_only_raises(self, tmp_path: Path) -> None:
        """Only val/ without train/ should raise FileNotFoundError."""
        from src.orchestration.tasks.data_tasks import prepare_dataset

        (tmp_path / "val").mkdir()
        with pytest.raises(FileNotFoundError, match="train.*val"):
            prepare_dataset.fn(str(tmp_path))
