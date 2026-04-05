"""Domain-agnostic protocols for Active Learning components.

These protocols define the contracts that domain-specific implementations
(CV, NLP, Tabular) must satisfy. The framework orchestrates the flow;
plugins provide the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ValidationReport:
    """Summary of dataset validation results."""

    total_images: int = 0
    issues_found: int = 0
    issue_types: dict[str, int] = field(default_factory=dict)
    health_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for MLflow logging."""
        return {
            "total_images": self.total_images,
            "issues_found": self.issues_found,
            "health_score": self.health_score,
            **{f"issue_{k}": v for k, v in self.issue_types.items()},
        }


@runtime_checkable
class UncertaintyEstimator(Protocol):
    """Measures prediction uncertainty.

    Domain-specific implementations compute uncertainty from model outputs.
    Higher scores indicate greater uncertainty.
    """

    def estimate(self, predictions: list[list[float]]) -> list[float]:
        """Compute uncertainty scores from model predictions.

        Args:
            predictions: Model output in domain-specific format.
                For CV: list of softmax probability vectors.

        Returns:
            Uncertainty scores in [0.0, 1.0], one per prediction.
        """
        ...


@runtime_checkable
class SampleSelector(Protocol):
    """Selects samples for human labeling from uncertain predictions.

    Implements query strategies such as top-K uncertainty, diversity
    sampling, or hybrid approaches.
    """

    def select(self, uncertainties: list[float], budget: int) -> list[int]:
        """Select indices of samples to send for labeling.

        Args:
            uncertainties: Uncertainty scores per sample.
            budget: Maximum number of samples to select.

        Returns:
            Indices of selected samples, ordered by priority.
        """
        ...


@runtime_checkable
class DataValidator(Protocol):
    """Validates domain-specific data quality.

    Implementations check for data issues relevant to their domain
    (e.g., image quality for CV, text quality for NLP).
    """

    def validate(self, dataset_path: Path) -> ValidationReport:
        """Run data quality validation on a dataset.

        Args:
            dataset_path: Path to dataset directory.

        Returns:
            ValidationReport with summary statistics.
        """
        ...


@runtime_checkable
class ModelTrainer(Protocol):
    """Trains domain-specific models.

    Implementations handle the full training loop including
    data loading, optimization, and experiment tracking.
    """

    def train(self, config: Any) -> dict[str, float]:  # noqa: ANN401
        """Run a full training loop.

        Args:
            config: Domain-specific training configuration.

        Returns:
            Dictionary of metric name → value pairs.
        """
        ...
