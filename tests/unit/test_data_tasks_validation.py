"""Unit tests for orchestration data tasks."""

from pathlib import Path

import pytest

from src.orchestration.tasks.data_tasks import prepare_dataset


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
