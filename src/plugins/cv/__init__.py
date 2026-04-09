"""CV (Computer Vision) plugin for the data-flywheel platform.

Provides image classification implementations of the core Protocol interfaces.
"""

from __future__ import annotations

from src.plugins.cv.sample_selector import UncertaintyDiversitySelector
from src.plugins.cv.uncertainty import SoftmaxEntropyEstimator
from src.plugins.loader import PluginBundle


def create_plugin() -> PluginBundle:
    """Create and return the CV plugin bundle."""
    return PluginBundle(
        uncertainty_estimator=SoftmaxEntropyEstimator,
        sample_selector=UncertaintyDiversitySelector,
        data_validator=None,
        model_trainer=None,
    )
