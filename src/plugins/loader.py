"""Environment-variable-based plugin loading.

Plugins are selected via the ``ACTIVE_PLUGIN`` environment variable
(default: ``"cv"``).  Each plugin package must expose a ``create_plugin()``
function that returns a :class:`PluginBundle`.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PluginBundle:
    """Bundle of Protocol implementation types provided by a plugin."""

    uncertainty_estimator: type[Any]
    sample_selector: type[Any] | None
    data_validator: type[Any] | None
    model_trainer: type[Any] | None


def load_plugin(plugin_name: str | None = None) -> PluginBundle:
    """Load a plugin by name and return its PluginBundle.

    When *plugin_name* is ``None`` (the default), the ``ACTIVE_PLUGIN``
    environment variable is read; if unset it falls back to ``"cv"``.

    Args:
        plugin_name: Name of the plugin package under ``src.plugins``.
            Defaults to ``os.getenv("ACTIVE_PLUGIN", "cv")``.

    Returns:
        PluginBundle with implementation types.

    Raises:
        ModuleNotFoundError: If the plugin package does not exist.
        AttributeError: If the plugin lacks ``create_plugin()``.
    """
    if plugin_name is None:
        plugin_name = os.getenv("ACTIVE_PLUGIN", "cv")
    module = importlib.import_module(f"src.plugins.{plugin_name}")
    return module.create_plugin()
