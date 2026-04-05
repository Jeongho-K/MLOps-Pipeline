"""Unit tests for device resolution and training error paths."""

from unittest.mock import patch

import pytest
import torch

from src.common.device import resolve_device


class TestResolveDevice:
    """Tests for resolve_device function."""

    def test_auto_cpu_fallback(self) -> None:
        """Auto should fall back to CPU when no GPU available."""
        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("torch.backends.mps.is_available", return_value=False),
        ):
            device = resolve_device("auto")
            assert device == torch.device("cpu")

    def test_auto_cuda(self) -> None:
        """Auto should prefer CUDA when available."""
        with patch("torch.cuda.is_available", return_value=True):
            device = resolve_device("auto")
            assert device == torch.device("cuda")

    def test_explicit_cpu(self) -> None:
        """Explicit 'cpu' should return CPU device."""
        device = resolve_device("cpu")
        assert device == torch.device("cpu")

    def test_explicit_cuda_unavailable_raises(self) -> None:
        """Requesting CUDA when unavailable should raise RuntimeError."""
        with (
            patch("torch.cuda.is_available", return_value=False),
            pytest.raises(RuntimeError, match="CUDA is not available"),
        ):
            resolve_device("cuda")

    def test_train_missing_data_dir(self) -> None:
        """Missing data directory should raise FileNotFoundError."""
        from src.plugins.cv.configs.train_config import TrainConfig
        from src.plugins.cv.trainer import train

        config = TrainConfig(data_dir="/nonexistent/path", device="cpu")
        with pytest.raises(FileNotFoundError, match="Training data not found"):
            train(config)
