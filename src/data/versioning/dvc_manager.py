"""Centralized DVC Python API wrapper for data versioning.

Replaces subprocess-based DVC CLI calls with the dvc.repo.Repo Python API.
Provides data integrity verification, MLflow cross-referencing, and
rollback support for Prefect transaction integration.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

import yaml

from src.data.versioning.config import DVCConfig
from src.data.versioning.models import VersioningResult

logger = logging.getLogger(__name__)


class DVCManager:
    """Centralized DVC operations using the Python API.

    Each Prefect task should create its own DVCManager instance
    and call close() when done (use try/finally).

    Args:
        config: DVC configuration. Defaults to DVCConfig() from environment.
    """

    def __init__(self, config: DVCConfig | None = None) -> None:
        self._config = config or DVCConfig()
        self._repo: Any = None  # dvc.repo.Repo, lazily initialized

    @property
    def repo(self) -> object:
        """Lazy-initialized DVC Repo instance."""
        if self._repo is None:
            from dvc.repo import Repo

            self._repo = Repo(self._config.repo_root)
        return self._repo

    def add(self, data_dir: str) -> str:
        """Track a directory or file with DVC.

        Args:
            data_dir: Path to the data directory or file to track.

        Returns:
            MD5 hash of the tracked data.

        Raises:
            FileNotFoundError: If data_dir does not exist.
            RuntimeError: If DVC add operation fails.
        """
        path = Path(data_dir)
        if not path.exists():
            raise FileNotFoundError(f"Data directory not found: {data_dir}")

        try:
            self.repo.add(str(path))
            logger.info("DVC add completed for %s", data_dir)
        except Exception as exc:
            raise RuntimeError(f"DVC add failed for {data_dir}: {exc}") from exc

        return self.get_data_hash(f"{data_dir}.dvc")

    def push(self) -> bool:
        """Push tracked data to the configured remote.

        Returns:
            True if push succeeded, False otherwise.
        """
        try:
            self.repo.push()
            logger.info("DVC push completed")
            return True
        except Exception:
            logger.warning("DVC push failed", exc_info=True)
            return False

    def pull(self, dvc_file: str) -> bool:
        """Pull data from the remote for a specific .dvc file.

        Args:
            dvc_file: Path to the .dvc file to pull data for.

        Returns:
            True if pull succeeded, False otherwise.

        Raises:
            FileNotFoundError: If the .dvc file does not exist.
        """
        if not Path(dvc_file).exists():
            raise FileNotFoundError(f"DVC file not found: {dvc_file}")

        try:
            self.repo.pull(targets=[dvc_file])
            logger.info("DVC pull completed for %s", dvc_file)
            return True
        except Exception:
            logger.warning("DVC pull failed for %s", dvc_file, exc_info=True)
            return False

    def verify_checksum(self, dvc_file: str) -> bool:
        """Verify local data matches the hash recorded in a .dvc file.

        Uses DVC status to check if the working tree matches the tracked state.
        An empty status result means data is in sync.

        Args:
            dvc_file: Path to the .dvc file to verify against.

        Returns:
            True if checksums match, False otherwise.

        Raises:
            FileNotFoundError: If the .dvc file does not exist.
        """
        if not Path(dvc_file).exists():
            raise FileNotFoundError(f"DVC file not found: {dvc_file}")

        try:
            status = self.repo.status(targets=[dvc_file])
            is_valid = len(status) == 0
            if is_valid:
                logger.info("Checksum verification passed for %s", dvc_file)
            else:
                logger.warning("Checksum verification failed for %s: %s", dvc_file, status)
            return is_valid
        except Exception:
            logger.warning("Checksum verification error for %s", dvc_file, exc_info=True)
            return False

    def get_data_hash(self, dvc_file: str) -> str:
        """Read the MD5 hash from a .dvc YAML file.

        Args:
            dvc_file: Path to the .dvc file.

        Returns:
            MD5 hash string, or empty string if not found.
        """
        path = Path(dvc_file)
        if not path.exists():
            return ""

        with open(path) as f:
            dvc_meta = yaml.safe_load(f)

        outs = dvc_meta.get("outs", [])
        if outs:
            return outs[0].get("md5", "")
        return ""

    def checkout(self, target: str | None = None) -> bool:
        """Restore data files to match .dvc file state.

        Used for rollback in Prefect transaction handlers.

        Args:
            target: Specific .dvc file or directory to checkout.
                If None, checks out all tracked data.

        Returns:
            True if checkout succeeded, False otherwise.
        """
        try:
            targets = [target] if target else None
            self.repo.checkout(targets=targets)
            logger.info("DVC checkout completed for %s", target or "all targets")
            return True
        except Exception:
            logger.warning("DVC checkout failed for %s", target, exc_info=True)
            return False

    def diff(self, rev_a: str = "HEAD", rev_b: str | None = None) -> dict[str, Any]:
        """Compare data between git revisions.

        Args:
            rev_a: Base revision (default: HEAD).
            rev_b: Target revision (default: current working tree).

        Returns:
            Dict with 'added', 'modified', 'deleted' keys listing changed files.
        """
        try:
            result = self.repo.diff(a_rev=rev_a, b_rev=rev_b)
            logger.info(
                "DVC diff %s..%s: %d added, %d modified, %d deleted",
                rev_a,
                rev_b or "workspace",
                len(result.get("added", [])),
                len(result.get("modified", [])),
                len(result.get("deleted", [])),
            )
            return result
        except Exception:
            logger.warning("DVC diff failed", exc_info=True)
            return {"added": [], "modified": [], "deleted": []}

    def tag_mlflow_run(
        self,
        run_id: str,
        data_hash: str,
        mlflow_tracking_uri: str,
        round_num: int | None = None,
    ) -> None:
        """Set DVC-related tags on an MLflow run for cross-system traceability.

        Args:
            run_id: MLflow run ID to tag.
            data_hash: DVC data hash to record.
            mlflow_tracking_uri: MLflow tracking server URI.
            round_num: Optional active learning round number.
        """
        if not run_id or not data_hash:
            return

        from mlflow import MlflowClient

        client = MlflowClient(mlflow_tracking_uri)
        client.set_tag(run_id, "dvc.data_hash", data_hash)
        if round_num is not None:
            client.set_tag(run_id, "dvc.round_num", str(round_num))
        logger.info("Tagged MLflow run %s with dvc.data_hash=%s", run_id, data_hash[:12])

    def version_round(
        self,
        data_dir: str,
        round_num: int,
        run_id: str = "",
        mlflow_tracking_uri: str = "",
    ) -> VersioningResult:
        """Full versioning workflow for one active learning round.

        Executes: add -> push (optional) -> verify -> tag MLflow.

        Args:
            data_dir: Path to the dataset directory.
            round_num: Current active learning round number.
            run_id: MLflow run ID for cross-referencing.
            mlflow_tracking_uri: MLflow tracking server URI.

        Returns:
            VersioningResult with operation outcomes.
        """
        result = VersioningResult(data_dir=data_dir, round_num=round_num)

        # Step 1: DVC add
        try:
            data_hash = self.add(data_dir)
            result.dvc_added = True
            result.data_hash = data_hash
        except (FileNotFoundError, RuntimeError):
            logger.warning("Round %d: DVC add failed for %s", round_num, data_dir, exc_info=True)
            return result

        # Step 2: DVC push (if configured)
        if self._config.push_to_remote:
            result.dvc_pushed = self.push()

        # Step 3: Verify checksum (if configured)
        dvc_file = f"{data_dir}.dvc"
        if self._config.verify_checksum and Path(dvc_file).exists():
            result.checksum_verified = self.verify_checksum(dvc_file)

        # Step 4: Tag MLflow run
        if run_id and mlflow_tracking_uri and result.data_hash:
            self.tag_mlflow_run(
                run_id=run_id,
                data_hash=result.data_hash,
                mlflow_tracking_uri=mlflow_tracking_uri,
                round_num=round_num,
            )

        logger.info(
            "Round %d versioning complete: hash=%s added=%s pushed=%s verified=%s",
            round_num,
            result.data_hash[:12] if result.data_hash else "N/A",
            result.dvc_added,
            result.dvc_pushed,
            result.checksum_verified,
        )

        return result

    def close(self) -> None:
        """Close the DVC repo instance and release resources."""
        if self._repo is not None:
            with contextlib.suppress(Exception):
                self._repo.close()
            self._repo = None
