"""Tests for plugin loading mechanism."""

from __future__ import annotations

import pytest

from src.plugins.loader import PluginBundle, load_plugin


class TestPluginLoader:
    """Plugin loader finds and loads plugins."""

    def test_load_unknown_plugin_raises(self):
        with pytest.raises(ModuleNotFoundError):
            load_plugin("nonexistent")

    def test_plugin_bundle_is_frozen(self):
        """PluginBundle should be immutable."""
        bundle = PluginBundle(
            uncertainty_estimator=object,
            sample_selector=None,
            data_validator=None,
            model_trainer=None,
        )
        with pytest.raises(AttributeError):
            bundle.uncertainty_estimator = None  # type: ignore[misc]
