"""Unit tests for serving API schemas."""

from src.core.serving.api.schemas import (
    HealthResponse,
    ModelInfoResponse,
    ModelReloadRequest,
    ModelReloadResponse,
    PredictionResponse,
)


class TestPredictionResponse:
    """Tests for PredictionResponse schema."""

    def test_basic_construction(self) -> None:
        """Should construct with required fields."""
        resp = PredictionResponse(
            predicted_class=2,
            confidence=0.95,
            probabilities=[0.02, 0.03, 0.95],
        )
        assert resp.predicted_class == 2
        assert resp.confidence == 0.95
        assert resp.class_name is None

    def test_with_class_name(self) -> None:
        """Should accept optional class_name."""
        resp = PredictionResponse(
            predicted_class=0,
            class_name="cat",
            confidence=0.8,
            probabilities=[0.8, 0.2],
        )
        assert resp.class_name == "cat"


class TestModelInfoResponse:
    """Tests for ModelInfoResponse schema."""

    def test_construction(self) -> None:
        """Should construct with all required fields."""
        info = ModelInfoResponse(
            model_name="resnet18",
            model_version="1",
            num_classes=10,
            device="cpu",
            image_size=224,
        )
        assert info.model_name == "resnet18"
        assert info.num_classes == 10


class TestModelReloadRequest:
    """Tests for ModelReloadRequest schema."""

    def test_defaults_to_none(self) -> None:
        """Both fields should default to None."""
        req = ModelReloadRequest()
        assert req.model_name is None
        assert req.model_version is None

    def test_with_values(self) -> None:
        """Should accept explicit values."""
        req = ModelReloadRequest(model_name="resnet50", model_version="2")
        assert req.model_name == "resnet50"
        assert req.model_version == "2"


class TestModelReloadResponse:
    """Tests for ModelReloadResponse schema."""

    def test_success_without_info(self) -> None:
        """Success response can have no model_info."""
        resp = ModelReloadResponse(status="ok", message="Reloaded")
        assert resp.model_info is None

    def test_success_response(self) -> None:
        """Success response should include model_info."""
        info = ModelInfoResponse(
            model_name="resnet18",
            model_version="1",
            num_classes=10,
            device="cpu",
            image_size=224,
        )
        resp = ModelReloadResponse(status="ok", message="Loaded", model_info=info)
        assert resp.model_info is not None
        assert resp.model_info.model_name == "resnet18"


class TestHealthResponse:
    """Tests for HealthResponse schema."""

    def test_healthy(self) -> None:
        """Should report model loaded status."""
        resp = HealthResponse(model_loaded=True)
        assert resp.status == "ok"
        assert resp.model_loaded is True

    def test_unhealthy(self) -> None:
        """Should report model not loaded."""
        resp = HealthResponse(model_loaded=False)
        assert resp.model_loaded is False
