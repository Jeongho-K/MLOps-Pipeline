"""Unit tests for Phase B continuous training tasks."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from src.core.orchestration.tasks.continuous_training_tasks import (
    check_champion_gate,
    check_training_quality,
    integrate_training_data,
    promote_to_champion,
    resolve_round_number,
)

# ---------------------------------------------------------------------------
# G2: Training Quality Gate
# ---------------------------------------------------------------------------


class TestCheckTrainingQuality:
    """Tests for check_training_quality (G2 gate)."""

    def test_passes_with_good_metrics(self) -> None:
        metrics = {
            "train_loss": 0.2,
            "train_accuracy": 0.92,
            "val_loss": 0.3,
            "val_accuracy": 0.85,
            "best_val_accuracy": 0.87,
        }
        result = check_training_quality.fn(
            metrics=metrics,
            min_val_accuracy=0.7,
            max_overfit_gap=0.15,
        )
        assert result["passed"] is True
        assert result["reason"] == "All checks passed"

    def test_fails_on_low_accuracy(self) -> None:
        metrics = {
            "train_loss": 0.5,
            "val_loss": 0.6,
            "val_accuracy": 0.55,
            "best_val_accuracy": 0.58,
        }
        result = check_training_quality.fn(
            metrics=metrics,
            min_val_accuracy=0.7,
        )
        assert result["passed"] is False
        assert "best_val_accuracy" in result["reason"]

    def test_fails_on_overfitting(self) -> None:
        metrics = {
            "train_loss": 0.1,
            "val_loss": 0.5,
            "val_accuracy": 0.75,
            "best_val_accuracy": 0.80,
        }
        result = check_training_quality.fn(
            metrics=metrics,
            min_val_accuracy=0.7,
            max_overfit_gap=0.15,
        )
        assert result["passed"] is False
        assert "overfit gap" in result["reason"]

    def test_skips_overfit_check_when_train_loss_missing(self) -> None:
        metrics = {
            "val_loss": 0.3,
            "val_accuracy": 0.85,
            "best_val_accuracy": 0.87,
        }
        result = check_training_quality.fn(
            metrics=metrics,
            min_val_accuracy=0.7,
        )
        assert result["passed"] is True
        assert result["checks"]["overfit_gap"]["value"] is None

    def test_fails_on_both_accuracy_and_overfitting(self) -> None:
        metrics = {
            "train_loss": 0.1,
            "val_loss": 0.8,
            "val_accuracy": 0.55,
            "best_val_accuracy": 0.58,
        }
        result = check_training_quality.fn(
            metrics=metrics,
            min_val_accuracy=0.7,
            max_overfit_gap=0.15,
        )
        assert result["passed"] is False
        assert "best_val_accuracy" in result["reason"]
        assert "overfit gap" in result["reason"]


# ---------------------------------------------------------------------------
# G3: Champion Gate
# ---------------------------------------------------------------------------


class TestCheckChampionGate:
    """Tests for check_champion_gate (G3 gate)."""

    def test_passes_when_challenger_is_better(self) -> None:
        challenger_metrics = {"best_val_accuracy": 0.90}

        mock_client = MagicMock()
        mock_version = MagicMock()
        mock_version.run_id = "run-123"
        mock_version.version = "3"
        mock_client.get_model_version_by_alias.return_value = mock_version

        mock_run = MagicMock()
        mock_run.data.metrics = {"best_val_accuracy": 0.85}
        mock_client.get_run.return_value = mock_run

        with (
            patch("src.core.orchestration.tasks.continuous_training_tasks.mlflow"),
            patch(
                "src.core.orchestration.tasks.continuous_training_tasks.MlflowClient",
                return_value=mock_client,
            ),
        ):
            result = check_champion_gate.fn(
                challenger_metrics=challenger_metrics,
                registered_model_name="cv-classifier",
                champion_metric="best_val_accuracy",
                champion_margin=0.0,
            )

        assert result["passed"] is True
        assert result["challenger_value"] == 0.90
        assert result["champion_value"] == 0.85

    def test_fails_when_challenger_is_worse(self) -> None:
        challenger_metrics = {"best_val_accuracy": 0.80}

        mock_client = MagicMock()
        mock_version = MagicMock()
        mock_version.run_id = "run-123"
        mock_version.version = "3"
        mock_client.get_model_version_by_alias.return_value = mock_version

        mock_run = MagicMock()
        mock_run.data.metrics = {"best_val_accuracy": 0.85}
        mock_client.get_run.return_value = mock_run

        with (
            patch("src.core.orchestration.tasks.continuous_training_tasks.mlflow"),
            patch(
                "src.core.orchestration.tasks.continuous_training_tasks.MlflowClient",
                return_value=mock_client,
            ),
        ):
            result = check_champion_gate.fn(
                challenger_metrics=challenger_metrics,
                registered_model_name="cv-classifier",
            )

        assert result["passed"] is False

    def test_auto_promotes_when_no_champion(self) -> None:
        from mlflow.exceptions import MlflowException

        challenger_metrics = {"best_val_accuracy": 0.75}

        mock_client = MagicMock()
        mock_client.get_model_version_by_alias.side_effect = MlflowException("not found")

        with (
            patch("src.core.orchestration.tasks.continuous_training_tasks.mlflow"),
            patch(
                "src.core.orchestration.tasks.continuous_training_tasks.MlflowClient",
                return_value=mock_client,
            ),
        ):
            result = check_champion_gate.fn(
                challenger_metrics=challenger_metrics,
                registered_model_name="cv-classifier",
            )

        assert result["passed"] is True
        assert "No existing champion" in result["reason"]

    def test_respects_margin(self) -> None:
        challenger_metrics = {"best_val_accuracy": 0.86}

        mock_client = MagicMock()
        mock_version = MagicMock()
        mock_version.run_id = "run-123"
        mock_version.version = "3"
        mock_client.get_model_version_by_alias.return_value = mock_version

        mock_run = MagicMock()
        mock_run.data.metrics = {"best_val_accuracy": 0.85}
        mock_client.get_run.return_value = mock_run

        with (
            patch("src.core.orchestration.tasks.continuous_training_tasks.mlflow"),
            patch(
                "src.core.orchestration.tasks.continuous_training_tasks.MlflowClient",
                return_value=mock_client,
            ),
        ):
            # With 0.02 margin, 0.86 > 0.85 + 0.02 is False
            result = check_champion_gate.fn(
                challenger_metrics=challenger_metrics,
                registered_model_name="cv-classifier",
                champion_margin=0.02,
            )

        assert result["passed"] is False

    def test_fails_when_challenger_metric_missing(self) -> None:
        with (
            patch("src.core.orchestration.tasks.continuous_training_tasks.mlflow"),
            patch("src.core.orchestration.tasks.continuous_training_tasks.MlflowClient"),
        ):
            result = check_champion_gate.fn(
                challenger_metrics={},
                registered_model_name="cv-classifier",
                champion_metric="best_val_accuracy",
            )

        assert result["passed"] is False
        assert "missing key" in result["reason"]


# ---------------------------------------------------------------------------
# Promote to Champion
# ---------------------------------------------------------------------------


class TestPromoteToChampion:
    """Tests for promote_to_champion task."""

    def test_sets_champion_alias(self) -> None:
        mock_client = MagicMock()
        mock_version = MagicMock()
        mock_version.version = "5"
        mock_version.run_id = "run-456"
        mock_client.get_model_version_by_alias.return_value = mock_version

        with (
            patch("src.core.orchestration.tasks.continuous_training_tasks.mlflow"),
            patch(
                "src.core.orchestration.tasks.continuous_training_tasks.MlflowClient",
                return_value=mock_client,
            ),
        ):
            result = promote_to_champion.fn(
                registered_model_name="cv-classifier",
            )

        mock_client.set_registered_model_alias.assert_called_once_with(
            name="cv-classifier",
            alias="champion",
            version="5",
        )
        assert result["version"] == "5"


# ---------------------------------------------------------------------------
# Round Number
# ---------------------------------------------------------------------------


class TestResolveRoundNumber:
    """Tests for resolve_round_number task."""

    def test_increments_from_existing_state(self) -> None:
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": BytesIO(json.dumps({"round": 3}).encode())}

        with patch(
            "src.core.orchestration.tasks.continuous_training_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = resolve_round_number.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
            )

        assert result == 4
        mock_client.put_object.assert_called_once()
        put_body = mock_client.put_object.call_args[1]["Body"]
        assert json.loads(put_body.decode())["round"] == 4

    def test_initializes_to_one_when_no_state(self) -> None:
        mock_client = MagicMock()
        mock_client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        mock_client.get_object.side_effect = mock_client.exceptions.NoSuchKey("not found")

        with patch(
            "src.core.orchestration.tasks.continuous_training_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = resolve_round_number.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
            )

        assert result == 1

    def test_uses_explicit_round(self) -> None:
        result = resolve_round_number.fn(
            s3_endpoint="http://minio:9000",
            s3_access_key="key",
            s3_secret_key="secret",
            explicit_round=7,
        )
        assert result == 7


# ---------------------------------------------------------------------------
# Data Integration
# ---------------------------------------------------------------------------


class TestIntegrateTrainingData:
    """Tests for integrate_training_data task."""

    def test_merges_human_and_pseudo_labels(self, tmp_path) -> None:
        output_dir = str(tmp_path / "merged")

        # Mock Label Studio annotations
        annotations = [
            {
                "data": {"image": "s3://bucket/img1.jpg"},
                "annotations": [{"result": [{"value": {"choices": ["cat"]}}]}],
            },
            {
                "data": {"image": "s3://bucket/img2.jpg"},
                "annotations": [{"result": [{"value": {"choices": ["dog"]}}]}],
            },
        ]

        # Mock S3 pseudo-labels
        pseudo_records = [
            {"class_name": "cat", "image_ref": "images/img3.jpg", "confidence": 0.98},
            {"class_name": "dog", "image_ref": "images/img4.jpg", "confidence": 0.97},
        ]
        jsonl_bytes = "\n".join(json.dumps(r) for r in pseudo_records).encode()

        mock_bridge = MagicMock()
        mock_bridge.get_completed_annotations.return_value = annotations

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": [{"Key": "accumulated/batch.jsonl"}]}]
        mock_s3.get_paginator.return_value = mock_paginator

        # Return different content based on key
        fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # JPEG-like bytes

        def mock_get_object(**kwargs):
            key = kwargs.get("Key", "")
            if key.endswith(".jsonl"):
                return {"Body": BytesIO(jsonl_bytes)}
            return {"Body": BytesIO(fake_image)}

        mock_s3.get_object.side_effect = mock_get_object

        with (
            patch(
                "src.core.active_learning.labeling.bridge.LabelStudioBridge",
                return_value=mock_bridge,
            ),
            patch(
                "src.core.orchestration.tasks.continuous_training_tasks.boto3.client",
                return_value=mock_s3,
            ),
        ):
            result = integrate_training_data.fn(
                label_studio_url="http://label-studio:8080",
                label_studio_api_key="key",
                label_studio_project_id=1,
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                output_dir=output_dir,
            )

        assert result["total_samples"] == 4
        assert result["human_labeled"] == 2
        assert result["pseudo_labeled"] == 2
        assert "cat" in result["classes"]
        assert "dog" in result["classes"]

        # Verify ImageFolder structure exists
        from pathlib import Path

        merged = Path(output_dir)
        assert (merged / "train").exists()
        assert (merged / "val").exists()

    def test_returns_empty_when_no_data(self, tmp_path) -> None:
        output_dir = str(tmp_path / "merged")

        mock_bridge = MagicMock()
        mock_bridge.get_completed_annotations.return_value = []

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_s3.get_paginator.return_value = mock_paginator

        with (
            patch(
                "src.core.active_learning.labeling.bridge.LabelStudioBridge",
                return_value=mock_bridge,
            ),
            patch(
                "src.core.orchestration.tasks.continuous_training_tasks.boto3.client",
                return_value=mock_s3,
            ),
        ):
            result = integrate_training_data.fn(
                label_studio_url="http://label-studio:8080",
                label_studio_api_key="key",
                label_studio_project_id=1,
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                output_dir=output_dir,
            )

        assert result["total_samples"] == 0
