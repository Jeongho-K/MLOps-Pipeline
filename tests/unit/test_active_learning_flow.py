"""Unit tests for Active Learning pipeline flow and tasks."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from src.core.orchestration.tasks.active_learning_tasks import (
    cleanup_accumulated,
    fetch_accumulated_samples,
    fetch_uncertain_predictions,
    select_samples_for_labeling,
    validate_accumulation_quality,
)


def _jsonl_bytes(*records) -> bytes:
    """Encode records as JSONL bytes."""
    return "\n".join(json.dumps(r) for r in records).encode("utf-8")


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------


class TestFetchUncertainPredictions:
    """Tests for fetch_uncertain_predictions task."""

    def test_filters_human_review_only(self):
        records = [
            {"predicted_class": 0, "confidence": 0.3, "uncertainty_score": 0.9, "routing_decision": "human_review"},
            {"predicted_class": 1, "confidence": 0.95, "uncertainty_score": 0.1, "routing_decision": "auto_accumulate"},
            {"predicted_class": 2, "confidence": 0.4, "uncertainty_score": 0.8, "routing_decision": "human_review"},
        ]

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": [{"Key": "2026-03-29/logs.jsonl"}]}]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.get_object.return_value = {"Body": BytesIO(_jsonl_bytes(*records))}

        with patch(
            "src.core.orchestration.tasks.active_learning_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = fetch_uncertain_predictions.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                bucket="prediction-logs",
                lookback_days=1,
            )

        assert len(result) == 2
        assert all(r["routing_decision"] == "human_review" for r in result)

    def test_returns_empty_when_no_logs(self):
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch(
            "src.core.orchestration.tasks.active_learning_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = fetch_uncertain_predictions.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                bucket="prediction-logs",
                lookback_days=1,
            )

        assert result == []

    def test_skips_non_jsonl_files(self):
        record = {"predicted_class": 0, "confidence": 0.3, "routing_decision": "human_review"}
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "2026-03-29/README.txt"}, {"Key": "2026-03-29/logs.jsonl"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.get_object.return_value = {"Body": BytesIO(_jsonl_bytes(record))}

        with patch(
            "src.core.orchestration.tasks.active_learning_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = fetch_uncertain_predictions.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                bucket="prediction-logs",
            )

        mock_client.get_object.assert_called_once()
        assert len(result) == 1


class TestSelectSamplesForLabeling:
    """Tests for select_samples_for_labeling task."""

    def test_sorts_by_uncertainty_descending(self):
        predictions = [
            {"uncertainty_score": 0.5},
            {"uncertainty_score": 0.9},
            {"uncertainty_score": 0.7},
        ]

        result = select_samples_for_labeling.fn(predictions=predictions, max_samples=3)

        assert result[0]["uncertainty_score"] == 0.9
        assert result[1]["uncertainty_score"] == 0.7
        assert result[2]["uncertainty_score"] == 0.5

    def test_limits_to_max_samples(self):
        predictions = [{"uncertainty_score": i * 0.1} for i in range(10)]

        result = select_samples_for_labeling.fn(predictions=predictions, max_samples=3)

        assert len(result) == 3

    def test_returns_empty_for_empty_input(self):
        result = select_samples_for_labeling.fn(predictions=[], max_samples=10)
        assert result == []


class TestCreateLabelingTasks:
    """Tests for create_labeling_tasks task."""

    def test_creates_tasks_via_bridge(self):
        from src.core.orchestration.tasks.active_learning_tasks import create_labeling_tasks

        samples = [{"image": "http://minio/img1.jpg"}, {"image": "http://minio/img2.jpg"}]
        mock_bridge = MagicMock()
        mock_bridge.create_tasks.return_value = [{"id": 1}, {"id": 2}]

        with patch(
            "src.core.active_learning.labeling.bridge.LabelStudioBridge",
            return_value=mock_bridge,
        ):
            result = create_labeling_tasks.fn(
                samples=samples,
                label_studio_url="http://label-studio:8080",
                label_studio_api_key="test-key",
                label_studio_project_id=1,
            )

        assert result["tasks_created"] == 2
        assert result["project_id"] == 1
        mock_bridge.create_tasks.assert_called_once_with(samples)
        mock_bridge.close.assert_called_once()

    def test_returns_zero_for_empty_samples(self):
        from src.core.orchestration.tasks.active_learning_tasks import create_labeling_tasks

        result = create_labeling_tasks.fn(
            samples=[],
            label_studio_url="http://label-studio:8080",
            label_studio_api_key="test-key",
            label_studio_project_id=1,
        )

        assert result["tasks_created"] == 0


class TestFetchAccumulatedSamples:
    """Tests for fetch_accumulated_samples task."""

    def test_fetches_jsonl_with_s3_key_annotation(self):
        records = [
            {"predicted_class": 0, "confidence": 0.98},
            {"predicted_class": 1, "confidence": 0.97},
        ]

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": [{"Key": "accumulated/batch1.jsonl"}]}]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.get_object.return_value = {"Body": BytesIO(_jsonl_bytes(*records))}

        with patch(
            "src.core.orchestration.tasks.active_learning_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = fetch_accumulated_samples.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                bucket="active-learning",
            )

        assert len(result) == 2
        assert all(r["_s3_key"] == "accumulated/batch1.jsonl" for r in result)

    def test_returns_empty_when_no_files(self):
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch(
            "src.core.orchestration.tasks.active_learning_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = fetch_accumulated_samples.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                bucket="active-learning",
            )

        assert result == []


class TestValidateAccumulationQuality:
    """Tests for validate_accumulation_quality task."""

    def _make_samples(self, classes, count_each):
        samples = []
        for cls in classes:
            for _ in range(count_each):
                samples.append({"predicted_class": cls, "confidence": 0.95})
        return samples

    def test_passes_with_good_distribution(self):
        samples = self._make_samples(["cat", "dog", "bird"], 30)  # 90 total

        result = validate_accumulation_quality.fn(
            samples=samples,
            existing_data_count=500,
            max_pseudo_label_ratio=0.3,
            min_samples=50,
        )

        assert result["passed"] is True
        assert result["reason"] == "All checks passed"

    def test_fails_below_min_samples(self):
        samples = self._make_samples(["cat", "dog"], 10)  # 20 total

        result = validate_accumulation_quality.fn(
            samples=samples,
            existing_data_count=500,
            min_samples=50,
        )

        assert result["passed"] is False
        assert "Insufficient samples" in result["reason"]

    def test_fails_on_class_imbalance(self):
        # 90% cat, 10% dog = imbalanced
        samples = [{"predicted_class": "cat", "confidence": 0.95}] * 90 + [
            {"predicted_class": "dog", "confidence": 0.95}
        ] * 10

        result = validate_accumulation_quality.fn(
            samples=samples,
            existing_data_count=500,
            min_samples=50,
        )

        assert result["passed"] is False
        assert "Class imbalance" in result["reason"]

    def test_fails_on_high_pseudo_ratio(self):
        samples = self._make_samples(["cat", "dog", "bird"], 40)  # 120 total

        result = validate_accumulation_quality.fn(
            samples=samples,
            existing_data_count=100,  # 120 / 220 = 54.5% > 30%
            max_pseudo_label_ratio=0.3,
            min_samples=50,
        )

        assert result["passed"] is False
        assert "Pseudo-label ratio" in result["reason"]


class TestCleanupAccumulated:
    """Tests for cleanup_accumulated task."""

    def test_deletes_specific_keys(self):
        mock_client = MagicMock()

        with patch(
            "src.core.orchestration.tasks.active_learning_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = cleanup_accumulated.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                bucket="active-learning",
                keys=["accumulated/a.jsonl", "accumulated/b.jsonl"],
            )

        assert result == 2
        mock_client.delete_objects.assert_called_once()

    def test_returns_zero_when_no_files(self):
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_client.get_paginator.return_value = mock_paginator

        with patch(
            "src.core.orchestration.tasks.active_learning_tasks.boto3.client",
            return_value=mock_client,
        ):
            result = cleanup_accumulated.fn(
                s3_endpoint="http://minio:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                bucket="active-learning",
            )

        assert result == 0


# ---------------------------------------------------------------------------
# Flow tests
# ---------------------------------------------------------------------------


class TestActiveLearningFlow:
    """Tests for active_learning_flow."""

    def test_flow_completes_with_uncertain_predictions(self):
        from src.core.orchestration.flows.active_learning_flow import active_learning_flow

        predictions = [
            {"uncertainty_score": 0.9, "routing_decision": "human_review"},
            {"uncertainty_score": 0.8, "routing_decision": "human_review"},
        ]

        with (
            patch(
                "src.core.orchestration.flows.active_learning_flow.fetch_uncertain_predictions",
                return_value=predictions,
            ),
            patch(
                "src.core.orchestration.flows.active_learning_flow.select_samples_for_labeling",
                return_value=predictions,
            ),
            patch(
                "src.core.orchestration.flows.active_learning_flow.create_labeling_tasks",
                return_value={"tasks_created": 2, "project_id": 1},
            ),
            patch("src.core.orchestration.flows.active_learning_flow.create_markdown_artifact"),
        ):
            result = active_learning_flow.fn()

        assert result["status"] == "completed"
        assert result["total_uncertain"] == 2
        assert result["selected"] == 2
        assert result["tasks_created"] == 2

    def test_flow_handles_no_uncertain_predictions(self):
        from src.core.orchestration.flows.active_learning_flow import active_learning_flow

        with (
            patch(
                "src.core.orchestration.flows.active_learning_flow.fetch_uncertain_predictions",
                return_value=[],
            ),
            patch("src.core.orchestration.flows.active_learning_flow.create_markdown_artifact"),
        ):
            result = active_learning_flow.fn()

        assert result["status"] == "completed"
        assert result["total_uncertain"] == 0
        assert result["selected"] == 0
        assert result["tasks_created"] == 0


# ---------------------------------------------------------------------------
# Data Accumulation Flow tests
# ---------------------------------------------------------------------------


# Data accumulation flow tests live in tests/unit/test_data_accumulation_flow.py
