"""Unit tests for the serving API endpoints."""

import io
from unittest.mock import MagicMock, patch

import torch
from fastapi.testclient import TestClient
from PIL import Image

from src.serving.api.app import create_app
from src.serving.api.config import ServingConfig
from src.serving.api.dependencies import ModelState


def _create_test_image() -> bytes:
    """Create a minimal test image in memory."""
    img = Image.new("RGB", (64, 64), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def _make_mock_model(num_classes: int = 3) -> MagicMock:
    """Create a mock model that returns fake logits."""
    model = MagicMock()
    model.fc = torch.nn.Linear(512, num_classes)
    model.side_effect = lambda x: torch.randn(x.shape[0], num_classes)
    return model


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_no_model(self) -> None:
        """Health should return model_loaded=false when no model."""
        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["model_loaded"] is False

    def test_health_with_model(self) -> None:
        """Health should return model_loaded=true when model is loaded."""
        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState(model=MagicMock(), model_name="test")

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["model_loaded"] is True


class TestModelInfoEndpoint:
    """Tests for GET /model/info."""

    def test_info_no_model(self) -> None:
        """Should return 503 when no model loaded."""
        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/model/info")
            assert resp.status_code == 503

    def test_info_with_model(self) -> None:
        """Should return model metadata when loaded."""
        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState(
            model=MagicMock(),
            model_name="resnet18",
            model_version="1",
            num_classes=10,
            device=torch.device("cpu"),
            image_size=224,
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/model/info")
            assert resp.status_code == 200
            data = resp.json()
            assert data["model_name"] == "resnet18"
            assert data["num_classes"] == 10


class TestPredictEndpoint:
    """Tests for POST /predict."""

    def test_predict_no_model(self) -> None:
        """Should return 503 when no model loaded."""
        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/predict", files={"file": ("test.png", _create_test_image())})
            assert resp.status_code == 503

    def test_predict_with_model(self) -> None:
        """Should return prediction when model is loaded."""
        config = ServingConfig(class_names="cat,dog,bird")
        app = create_app(config, enable_lifespan=False)

        mock_model = _make_mock_model(num_classes=3)
        app.state.model_state = ModelState(
            model=mock_model,
            model_name="test-model",
            model_version="1",
            num_classes=3,
            device=torch.device("cpu"),
            image_size=224,
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/predict", files={"file": ("test.png", _create_test_image())})
            assert resp.status_code == 200
            data = resp.json()
            assert "predicted_class" in data
            assert "confidence" in data
            assert "probabilities" in data
            assert len(data["probabilities"]) == 3
            assert data["class_name"] in ("cat", "dog", "bird")

    def test_predict_invalid_image(self) -> None:
        """Should return 400 for non-image data."""
        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState(
            model=MagicMock(),
            model_name="test",
            model_version="1",
            num_classes=3,
            device=torch.device("cpu"),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/predict", files={"file": ("test.txt", b"not an image")})
            assert resp.status_code == 400


class TestModelReloadEndpoint:
    """Tests for POST /model/reload."""

    @patch("src.serving.api.routes.load_model_from_registry")
    def test_reload_success(self, mock_load) -> None:
        """Should reload model and return new info."""
        new_state = ModelState(
            model=MagicMock(),
            model_name="resnet50",
            model_version="2",
            num_classes=20,
            device=torch.device("cpu"),
            image_size=224,
        )
        mock_load.return_value = new_state

        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState(
            model=MagicMock(),
            model_name="resnet18",
            model_version="1",
            num_classes=10,
            device=torch.device("cpu"),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/model/reload", json={"model_name": "resnet50", "model_version": "2"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["model_info"]["model_name"] == "resnet50"

    @patch("src.serving.api.routes.load_model_from_registry", side_effect=RuntimeError("MLflow down"))
    def test_reload_failure(self, _mock_load) -> None:
        """Should return error status on failure."""
        config = ServingConfig()
        app = create_app(config, enable_lifespan=False)
        app.state.model_state = ModelState(
            model=MagicMock(),
            model_name="resnet18",
            model_version="1",
            device=torch.device("cpu"),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/model/reload", json={"model_name": "bad-model"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "error"
