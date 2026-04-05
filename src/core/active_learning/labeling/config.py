"""Labeling-specific configuration.

Re-exports ActiveLearningConfig which already contains Label Studio settings
(label_studio_url, label_studio_api_key, label_studio_project_id).
"""

from __future__ import annotations

from src.core.active_learning.config import ActiveLearningConfig

__all__ = ["ActiveLearningConfig"]
