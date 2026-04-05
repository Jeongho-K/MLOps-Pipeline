"""Unit tests for DVC integration in orchestration data tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from src.core.orchestration.tasks.data_tasks import ensure_data_available


class TestEnsureDataAvailableWithDVC:
    """Tests for ensure_data_available using DVCManager."""

    def test_existing_data_skips_pull(self, tmp_path: Path) -> None:
        """When data directory exists, no DVC pull should occur."""
        data_dir = tmp_path / "dataset"
        data_dir.mkdir()

        result = ensure_data_available.fn(str(data_dir))
        assert result == data_dir

    def test_no_dvc_file_raises(self, tmp_path: Path) -> None:
        """When neither data dir nor .dvc file exists, raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="DVC file"):
            ensure_data_available.fn(str(tmp_path / "nonexistent"))

    def test_pulls_from_dvc(self, tmp_path: Path) -> None:
        """When data is missing but .dvc file exists, should pull via DVCManager."""
        data_dir = tmp_path / "dataset"
        dvc_file = tmp_path / "dataset.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")

        mock_manager = MagicMock()
        mock_manager.pull.return_value = True
        mock_manager.verify_checksum.return_value = True

        with patch("src.core.data.versioning.DVCManager", return_value=mock_manager):
            result = ensure_data_available.fn(str(data_dir))

        mock_manager.pull.assert_called_once_with(str(dvc_file))
        mock_manager.verify_checksum.assert_called_once_with(str(dvc_file))
        mock_manager.close.assert_called_once()
        assert result == data_dir

    def test_checksum_failure_raises(self, tmp_path: Path) -> None:
        """When checksum verification fails, should raise RuntimeError."""
        data_dir = tmp_path / "dataset"
        dvc_file = tmp_path / "dataset.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")

        mock_manager = MagicMock()
        mock_manager.pull.return_value = True
        mock_manager.verify_checksum.return_value = False

        with (
            patch("src.core.data.versioning.DVCManager", return_value=mock_manager),
            pytest.raises(RuntimeError, match="Checksum verification failed"),
        ):
            ensure_data_available.fn(str(data_dir))

        mock_manager.close.assert_called_once()

    def test_pull_failure_raises(self, tmp_path: Path) -> None:
        """When DVC pull fails, should raise RuntimeError."""
        data_dir = tmp_path / "dataset"
        dvc_file = tmp_path / "dataset.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")

        mock_manager = MagicMock()
        mock_manager.pull.return_value = False

        with (
            patch("src.core.data.versioning.DVCManager", return_value=mock_manager),
            pytest.raises(RuntimeError, match="DVC pull failed"),
        ):
            ensure_data_available.fn(str(data_dir))

        mock_manager.close.assert_called_once()

    def test_skip_verification(self, tmp_path: Path) -> None:
        """When verify=False, should skip checksum verification."""
        data_dir = tmp_path / "dataset"
        dvc_file = tmp_path / "dataset.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")

        mock_manager = MagicMock()
        mock_manager.pull.return_value = True

        with patch("src.core.data.versioning.DVCManager", return_value=mock_manager):
            ensure_data_available.fn(str(data_dir), verify=False)

        mock_manager.verify_checksum.assert_not_called()
        mock_manager.close.assert_called_once()

    def test_close_called_on_exception(self, tmp_path: Path) -> None:
        """Manager.close() should be called even if an exception occurs."""
        data_dir = tmp_path / "dataset"
        dvc_file = tmp_path / "dataset.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")

        mock_manager = MagicMock()
        mock_manager.pull.side_effect = Exception("Unexpected error")

        with (
            patch("src.core.data.versioning.DVCManager", return_value=mock_manager),
            pytest.raises(Exception, match="Unexpected error"),
        ):
            ensure_data_available.fn(str(data_dir))

        mock_manager.close.assert_called_once()
