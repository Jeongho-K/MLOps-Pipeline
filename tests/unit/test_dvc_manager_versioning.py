"""Unit tests for DVCManager and versioning data models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.core.data.versioning.config import DVCConfig
from src.core.data.versioning.dvc_manager import DVCManager
from src.core.data.versioning.models import RoundSnapshot, VersioningResult

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dvc_config(tmp_path: Path) -> DVCConfig:
    """DVCConfig pointing to tmp_path as repo root."""
    return DVCConfig(repo_root=str(tmp_path), push_to_remote=True, verify_checksum=True)


@pytest.fixture()
def mock_repo() -> MagicMock:
    """Mock dvc.repo.Repo instance."""
    repo = MagicMock()
    repo.add.return_value = None
    repo.push.return_value = None
    repo.pull.return_value = None
    repo.checkout.return_value = None
    repo.status.return_value = {}
    repo.diff.return_value = {"added": [], "modified": [], "deleted": []}
    repo.close.return_value = None
    return repo


@pytest.fixture()
def manager(dvc_config: DVCConfig, mock_repo: MagicMock) -> DVCManager:
    """DVCManager with a mocked Repo."""
    mgr = DVCManager(config=dvc_config)
    mgr._repo = mock_repo
    return mgr


def _write_dvc_file(path: Path, md5: str = "abc123") -> Path:
    """Write a minimal .dvc YAML file and return its path."""
    dvc_file = path.with_suffix(path.suffix + ".dvc") if not str(path).endswith(".dvc") else path
    dvc_file.write_text(yaml.dump({"outs": [{"md5": md5, "path": path.name}]}))
    return dvc_file


# ---------------------------------------------------------------------------
# DVCConfig
# ---------------------------------------------------------------------------


class TestDVCConfig:
    """Tests for DVCConfig."""

    def test_defaults(self) -> None:
        """Default values should be set."""
        config = DVCConfig()
        assert config.remote_name == "minio-remote"
        assert config.repo_root == "."
        assert config.push_to_remote is True
        assert config.verify_checksum is True

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables with DVC_ prefix should override defaults."""
        monkeypatch.setenv("DVC_REMOTE_NAME", "my-remote")
        monkeypatch.setenv("DVC_PUSH_TO_REMOTE", "false")
        config = DVCConfig()
        assert config.remote_name == "my-remote"
        assert config.push_to_remote is False


# ---------------------------------------------------------------------------
# DVCManager Init
# ---------------------------------------------------------------------------


class TestDVCManagerInit:
    """Tests for DVCManager initialization."""

    def test_lazy_repo_initialization(self) -> None:
        """Repo should not be created until first access."""
        mgr = DVCManager(config=DVCConfig())
        assert mgr._repo is None

    def test_repo_property_creates_instance(self) -> None:
        """Accessing .repo property should create Repo instance."""
        with patch("dvc.repo.Repo") as mock_repo_cls:
            mock_repo_cls.return_value = MagicMock()
            mgr = DVCManager(config=DVCConfig(repo_root="/tmp/test"))
            _ = mgr.repo
            mock_repo_cls.assert_called_once_with("/tmp/test")

    def test_default_config(self) -> None:
        """DVCManager without config should use DVCConfig defaults."""
        mgr = DVCManager()
        assert mgr._config.remote_name == "minio-remote"


# ---------------------------------------------------------------------------
# DVCManager.add()
# ---------------------------------------------------------------------------


class TestDVCManagerAdd:
    """Tests for DVCManager.add()."""

    def test_add_returns_hash(self, manager: DVCManager, tmp_path: Path) -> None:
        """add() should return the MD5 hash from the generated .dvc file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_dvc_file(data_dir, md5="deadbeef123")

        result = manager.add(str(data_dir))
        assert result == "deadbeef123"
        manager.repo.add.assert_called_once_with(str(data_dir))

    def test_add_nonexistent_dir_raises(self, manager: DVCManager) -> None:
        """add() should raise FileNotFoundError for non-existent directory."""
        with pytest.raises(FileNotFoundError, match="Data directory not found"):
            manager.add("/nonexistent/path")

    def test_add_repo_failure_raises(self, manager: DVCManager, tmp_path: Path) -> None:
        """add() should raise RuntimeError when repo.add() fails."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        manager.repo.add.side_effect = Exception("DVC internal error")

        with pytest.raises(RuntimeError, match="DVC add failed"):
            manager.add(str(data_dir))


# ---------------------------------------------------------------------------
# DVCManager.push()
# ---------------------------------------------------------------------------


class TestDVCManagerPush:
    """Tests for DVCManager.push()."""

    def test_push_success(self, manager: DVCManager) -> None:
        """push() should return True on success."""
        assert manager.push() is True
        manager.repo.push.assert_called_once()

    def test_push_failure(self, manager: DVCManager) -> None:
        """push() should return False on failure."""
        manager.repo.push.side_effect = Exception("Network error")
        assert manager.push() is False


# ---------------------------------------------------------------------------
# DVCManager.pull()
# ---------------------------------------------------------------------------


class TestDVCManagerPull:
    """Tests for DVCManager.pull()."""

    def test_pull_success(self, manager: DVCManager, tmp_path: Path) -> None:
        """pull() should return True on success."""
        dvc_file = tmp_path / "data.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")

        assert manager.pull(str(dvc_file)) is True
        manager.repo.pull.assert_called_once_with(targets=[str(dvc_file)])

    def test_pull_nonexistent_file_raises(self, manager: DVCManager) -> None:
        """pull() should raise FileNotFoundError for missing .dvc file."""
        with pytest.raises(FileNotFoundError, match="DVC file not found"):
            manager.pull("/nonexistent/file.dvc")

    def test_pull_failure(self, manager: DVCManager, tmp_path: Path) -> None:
        """pull() should return False on failure."""
        dvc_file = tmp_path / "data.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")
        manager.repo.pull.side_effect = Exception("Remote unreachable")

        assert manager.pull(str(dvc_file)) is False


# ---------------------------------------------------------------------------
# DVCManager.verify_checksum()
# ---------------------------------------------------------------------------


class TestDVCManagerVerifyChecksum:
    """Tests for DVCManager.verify_checksum()."""

    def test_matching_checksum(self, manager: DVCManager, tmp_path: Path) -> None:
        """verify_checksum() should return True when data matches."""
        dvc_file = tmp_path / "data.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")
        manager.repo.status.return_value = {}

        assert manager.verify_checksum(str(dvc_file)) is True

    def test_mismatched_checksum(self, manager: DVCManager, tmp_path: Path) -> None:
        """verify_checksum() should return False when data differs."""
        dvc_file = tmp_path / "data.dvc"
        dvc_file.write_text("outs:\n  - md5: abc123\n")
        manager.repo.status.return_value = {"data": [{"changed outs": {"data": "modified"}}]}

        assert manager.verify_checksum(str(dvc_file)) is False

    def test_missing_file_raises(self, manager: DVCManager) -> None:
        """verify_checksum() should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="DVC file not found"):
            manager.verify_checksum("/nonexistent/file.dvc")


# ---------------------------------------------------------------------------
# DVCManager.get_data_hash()
# ---------------------------------------------------------------------------


class TestDVCManagerGetDataHash:
    """Tests for DVCManager.get_data_hash()."""

    def test_reads_hash(self, manager: DVCManager, tmp_path: Path) -> None:
        """get_data_hash() should extract MD5 from .dvc file."""
        dvc_file = tmp_path / "data.dvc"
        dvc_file.write_text(yaml.dump({"outs": [{"md5": "hash_value_123", "path": "data"}]}))

        assert manager.get_data_hash(str(dvc_file)) == "hash_value_123"

    def test_missing_file_returns_empty(self, manager: DVCManager) -> None:
        """get_data_hash() should return empty string for missing file."""
        assert manager.get_data_hash("/nonexistent.dvc") == ""

    def test_empty_outs_returns_empty(self, manager: DVCManager, tmp_path: Path) -> None:
        """get_data_hash() should return empty string when outs is empty."""
        dvc_file = tmp_path / "data.dvc"
        dvc_file.write_text(yaml.dump({"outs": []}))

        assert manager.get_data_hash(str(dvc_file)) == ""


# ---------------------------------------------------------------------------
# DVCManager.checkout()
# ---------------------------------------------------------------------------


class TestDVCManagerCheckout:
    """Tests for DVCManager.checkout()."""

    def test_checkout_with_target(self, manager: DVCManager) -> None:
        """checkout() should call repo.checkout with specific target."""
        assert manager.checkout(target="data/raw") is True
        manager.repo.checkout.assert_called_once_with(targets=["data/raw"])

    def test_checkout_all(self, manager: DVCManager) -> None:
        """checkout() without target should checkout all."""
        assert manager.checkout() is True
        manager.repo.checkout.assert_called_once_with(targets=None)

    def test_checkout_failure(self, manager: DVCManager) -> None:
        """checkout() should return False on failure."""
        manager.repo.checkout.side_effect = Exception("Checkout error")
        assert manager.checkout(target="data") is False


# ---------------------------------------------------------------------------
# DVCManager.diff()
# ---------------------------------------------------------------------------


class TestDVCManagerDiff:
    """Tests for DVCManager.diff()."""

    def test_diff_returns_structured_result(self, manager: DVCManager) -> None:
        """diff() should return dict with added/modified/deleted keys."""
        manager.repo.diff.return_value = {
            "added": [{"path": "data/new.png"}],
            "modified": [],
            "deleted": [{"path": "data/old.png"}],
        }

        result = manager.diff(rev_a="HEAD~1")
        assert len(result["added"]) == 1
        assert len(result["deleted"]) == 1
        manager.repo.diff.assert_called_once_with(a_rev="HEAD~1", b_rev=None)

    def test_diff_failure_returns_empty(self, manager: DVCManager) -> None:
        """diff() should return empty structure on failure."""
        manager.repo.diff.side_effect = Exception("Diff error")
        result = manager.diff()
        assert result == {"added": [], "modified": [], "deleted": []}


# ---------------------------------------------------------------------------
# DVCManager.tag_mlflow_run()
# ---------------------------------------------------------------------------


class TestDVCManagerTagMLflow:
    """Tests for DVCManager.tag_mlflow_run()."""

    def test_tags_run_with_data_hash(self, manager: DVCManager) -> None:
        """tag_mlflow_run() should set dvc.data_hash tag."""
        with patch("mlflow.MlflowClient") as mock_cls:
            mock_client = mock_cls.return_value
            manager.tag_mlflow_run("run-123", "hashABC", "http://mlflow:5000")

            mock_client.set_tag.assert_any_call("run-123", "dvc.data_hash", "hashABC")

    def test_tags_run_with_round_number(self, manager: DVCManager) -> None:
        """tag_mlflow_run() should set dvc.round_num tag when provided."""
        with patch("mlflow.MlflowClient") as mock_cls:
            mock_client = mock_cls.return_value
            manager.tag_mlflow_run("run-123", "hashABC", "http://mlflow:5000", round_num=5)

            mock_client.set_tag.assert_any_call("run-123", "dvc.round_num", "5")

    def test_skips_when_no_run_id(self, manager: DVCManager) -> None:
        """tag_mlflow_run() should skip when run_id is empty."""
        with patch("mlflow.MlflowClient") as mock_cls:
            manager.tag_mlflow_run("", "hashABC", "http://mlflow:5000")
            mock_cls.assert_not_called()

    def test_skips_when_no_hash(self, manager: DVCManager) -> None:
        """tag_mlflow_run() should skip when data_hash is empty."""
        with patch("mlflow.MlflowClient") as mock_cls:
            manager.tag_mlflow_run("run-123", "", "http://mlflow:5000")
            mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# DVCManager.version_round()
# ---------------------------------------------------------------------------


class TestDVCManagerVersionRound:
    """Tests for DVCManager.version_round()."""

    def test_full_workflow(self, manager: DVCManager, tmp_path: Path) -> None:
        """version_round() should execute add -> push -> verify -> tag."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_dvc_file(data_dir, md5="round1hash")

        with patch.object(manager, "tag_mlflow_run") as mock_tag:
            result = manager.version_round(
                data_dir=str(data_dir),
                round_num=1,
                run_id="run-abc",
                mlflow_tracking_uri="http://mlflow:5000",
            )

        assert result.dvc_added is True
        assert result.data_hash == "round1hash"
        assert result.dvc_pushed is True
        assert result.checksum_verified is True
        assert result.round_num == 1
        mock_tag.assert_called_once()

    def test_workflow_without_push(self, tmp_path: Path, mock_repo: MagicMock) -> None:
        """version_round() should skip push when push_to_remote is False."""
        config = DVCConfig(repo_root=str(tmp_path), push_to_remote=False)
        mgr = DVCManager(config=config)
        mgr._repo = mock_repo

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_dvc_file(data_dir, md5="nopush_hash")

        result = mgr.version_round(data_dir=str(data_dir), round_num=2)

        assert result.dvc_added is True
        assert result.dvc_pushed is False
        mock_repo.push.assert_not_called()

    def test_add_failure_returns_early(self, manager: DVCManager) -> None:
        """version_round() should return early result when add fails."""
        result = manager.version_round(data_dir="/nonexistent", round_num=1)

        assert result.dvc_added is False
        assert result.data_hash == ""
        manager.repo.push.assert_not_called()


# ---------------------------------------------------------------------------
# DVCManager.close()
# ---------------------------------------------------------------------------


class TestDVCManagerClose:
    """Tests for DVCManager.close()."""

    def test_close_releases_repo(self, manager: DVCManager) -> None:
        """close() should close repo and set to None."""
        manager.close()
        assert manager._repo is None

    def test_close_idempotent(self, manager: DVCManager) -> None:
        """close() should be safe to call multiple times."""
        manager.close()
        manager.close()
        assert manager._repo is None


# ---------------------------------------------------------------------------
# VersioningResult
# ---------------------------------------------------------------------------


class TestVersioningResult:
    """Tests for VersioningResult dataclass."""

    def test_to_dict(self) -> None:
        """to_dict() should return all expected keys."""
        result = VersioningResult(data_dir="data/raw", data_hash="abc", round_num=3)
        d = result.to_dict()

        assert d["data_dir"] == "data/raw"
        assert d["data_hash"] == "abc"
        assert d["round_num"] == 3
        assert "timestamp" in d
        assert d["timestamp"] != ""

    def test_defaults(self) -> None:
        """Default values should be set correctly."""
        result = VersioningResult(data_dir="data")
        assert result.dvc_added is False
        assert result.dvc_pushed is False
        assert result.checksum_verified is False

    def test_auto_timestamp(self) -> None:
        """Timestamp should be set automatically."""
        result = VersioningResult(data_dir="data")
        assert result.timestamp != ""


# ---------------------------------------------------------------------------
# RoundSnapshot
# ---------------------------------------------------------------------------


class TestRoundSnapshot:
    """Tests for RoundSnapshot dataclass."""

    def test_to_dict(self) -> None:
        """to_dict() should return all expected keys."""
        snap = RoundSnapshot(
            round_num=2,
            data_hash="hash456",
            sample_count=500,
            stage="post-image-clean",
            images_removed=10,
            previous_hash="hash123",
        )
        d = snap.to_dict()

        assert d["round_num"] == 2
        assert d["data_hash"] == "hash456"
        assert d["sample_count"] == 500
        assert d["stage"] == "post-image-clean"
        assert d["images_removed"] == 10
        assert d["previous_hash"] == "hash123"

    def test_chain_previous_hash(self) -> None:
        """RoundSnapshot should chain previous_hash for evolution tracking."""
        snap1 = RoundSnapshot(round_num=1, data_hash="h1", sample_count=100)
        snap2 = RoundSnapshot(
            round_num=1,
            data_hash="h2",
            sample_count=95,
            previous_hash=snap1.data_hash,
        )
        assert snap2.previous_hash == "h1"

    def test_cleaning_stats(self) -> None:
        """cleaning_stats should store arbitrary metadata."""
        snap = RoundSnapshot(
            round_num=1,
            data_hash="h1",
            sample_count=100,
            cleaning_stats={"blurry": 3, "dark": 2},
        )
        assert snap.cleaning_stats["blurry"] == 3
