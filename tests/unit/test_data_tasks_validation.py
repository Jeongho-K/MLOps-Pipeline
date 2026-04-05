"""Unit tests for orchestration data tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from src.core.orchestration.tasks.data_tasks import prepare_dataset


class TestPrepareDataset:
    """Tests for prepare_dataset task."""

    def test_nonexistent_dir_raises(self, tmp_path: Path) -> None:
        """Non-existent directory should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Dataset directory not found"):
            prepare_dataset.fn(str(tmp_path / "nonexistent"))

    def test_missing_splits_raises(self, tmp_path: Path) -> None:
        """Directory without train/val should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="train.*val"):
            prepare_dataset.fn(str(tmp_path))

    def test_valid_dataset(self, tmp_path: Path) -> None:
        """Valid dataset structure should return the path."""
        train_dir = tmp_path / "train" / "class0"
        val_dir = tmp_path / "val" / "class0"
        train_dir.mkdir(parents=True)
        val_dir.mkdir(parents=True)
        (train_dir / "img.png").touch()
        (val_dir / "img.png").touch()

        result = prepare_dataset.fn(str(tmp_path))
        assert result == tmp_path


class TestValidateLabelsTask:
    """Tests for validate_labels_task (post-hoc label validation)."""

    @staticmethod
    def _mock_label_report() -> dict[str, Any]:
        """Create a mock LabelReport.to_dict() result."""
        return {
            "total_samples": 100,
            "label_issues_found": 5,
            "label_issue_rate": 0.05,
            "avg_label_quality": 0.92,
        }

    @staticmethod
    def _make_mock_batch() -> tuple[Any, Any]:
        """Create a mock (images, targets) batch for DataLoader iteration."""
        import torch

        images = torch.randn(4, 3, 224, 224)
        targets = torch.tensor([0, 1, 0, 1])
        return images, targets

    @staticmethod
    def _make_mock_model(num_classes: int = 2) -> MagicMock:
        """Create a mock model that returns real tensors for softmax compatibility."""
        import torch

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.return_value = torch.randn(4, num_classes)
        return mock_model

    def _common_patches(self, mock_model: MagicMock, mock_report: MagicMock) -> dict[str, Any]:
        """Return dict of patch context managers for validate_labels_task."""
        batch = self._make_mock_batch()
        return {
            "load_model": patch("mlflow.pytorch.load_model", return_value=mock_model),
            "set_tracking_uri": patch("mlflow.set_tracking_uri"),
            "image_folder": patch("src.core.orchestration.tasks.data_tasks.ImageFolder"),
            "data_loader": patch("src.core.orchestration.tasks.data_tasks.DataLoader", return_value=[batch]),
            "get_transforms": patch("src.plugins.cv.transforms.get_eval_transforms", return_value=MagicMock()),
            "validate_labels": patch("src.plugins.cv.label_validator.validate_labels", return_value=mock_report),
            "create_artifact": patch("src.core.orchestration.tasks.data_tasks.create_markdown_artifact"),
        }

    def test_returns_label_quality_dict(self, tmp_path: Path) -> None:
        """Returns dict with expected label quality metric keys."""
        from src.core.orchestration.tasks.data_tasks import validate_labels_task

        mock_report = MagicMock()
        mock_report.to_dict.return_value = self._mock_label_report()
        mock_model = self._make_mock_model()

        (tmp_path / "train" / "class0").mkdir(parents=True)

        patches = self._common_patches(mock_model, mock_report)
        with (
            patches["load_model"],
            patches["set_tracking_uri"],
            patches["image_folder"],
            patches["data_loader"],
            patches["get_transforms"],
            patches["validate_labels"],
            patches["create_artifact"],
        ):
            result = validate_labels_task.fn(
                model_uri="models:/test-model@challenger",
                data_dir=str(tmp_path),
                device="cpu",
                num_classes=2,
                mlflow_tracking_uri="http://mlflow:5000",
            )

        expected_keys = {"total_samples", "label_issues_found", "label_issue_rate", "avg_label_quality"}
        assert set(result.keys()) == expected_keys
        assert result["total_samples"] == 100

    def test_model_loaded_and_set_to_eval_mode(self, tmp_path: Path) -> None:
        """Model is loaded from MLflow URI and set to eval mode."""
        from src.core.orchestration.tasks.data_tasks import validate_labels_task

        mock_report = MagicMock()
        mock_report.to_dict.return_value = self._mock_label_report()
        mock_model = self._make_mock_model()

        (tmp_path / "train" / "class0").mkdir(parents=True)

        patches = self._common_patches(mock_model, mock_report)
        with (
            patches["load_model"] as mock_load,
            patches["set_tracking_uri"],
            patches["image_folder"],
            patches["data_loader"],
            patches["get_transforms"],
            patches["validate_labels"],
            patches["create_artifact"],
        ):
            validate_labels_task.fn(
                model_uri="models:/test-model@challenger",
                data_dir=str(tmp_path),
                device="cpu",
                num_classes=2,
                mlflow_tracking_uri="http://mlflow:5000",
            )

        mock_load.assert_called_once_with("models:/test-model@challenger", map_location="cpu")
        mock_model.eval.assert_called_once()

    def test_mlflow_logging_with_run_id(self, tmp_path: Path) -> None:
        """When mlflow_run_id is provided, metrics are logged to MLflow."""
        from src.core.orchestration.tasks.data_tasks import validate_labels_task

        mock_report = MagicMock()
        mock_report.to_dict.return_value = self._mock_label_report()
        mock_model = self._make_mock_model()

        (tmp_path / "train" / "class0").mkdir(parents=True)

        patches = self._common_patches(mock_model, mock_report)
        with (
            patches["load_model"],
            patches["set_tracking_uri"],
            patches["image_folder"],
            patches["data_loader"],
            patches["get_transforms"],
            patches["validate_labels"],
            patches["create_artifact"],
            patch("mlflow.MlflowClient") as mock_client_cls,
        ):
            validate_labels_task.fn(
                model_uri="models:/test-model@challenger",
                data_dir=str(tmp_path),
                device="cpu",
                num_classes=2,
                mlflow_run_id="run-abc",
                mlflow_tracking_uri="http://mlflow:5000",
            )

        mock_client = mock_client_cls.return_value
        assert mock_client.log_metric.call_count == 3

    def test_skips_mlflow_when_no_run_id(self, tmp_path: Path) -> None:
        """When mlflow_run_id is None, MlflowClient is not called."""
        from src.core.orchestration.tasks.data_tasks import validate_labels_task

        mock_report = MagicMock()
        mock_report.to_dict.return_value = self._mock_label_report()
        mock_model = self._make_mock_model()

        (tmp_path / "train" / "class0").mkdir(parents=True)

        patches = self._common_patches(mock_model, mock_report)
        with (
            patches["load_model"],
            patches["set_tracking_uri"],
            patches["image_folder"],
            patches["data_loader"],
            patches["get_transforms"],
            patches["validate_labels"],
            patches["create_artifact"],
        ):
            validate_labels_task.fn(
                model_uri="models:/test-model@challenger",
                data_dir=str(tmp_path),
                device="cpu",
                num_classes=2,
                mlflow_run_id=None,
                mlflow_tracking_uri="http://mlflow:5000",
            )
