"""Data models for the auto-accumulator."""

from __future__ import annotations

import dataclasses
import json


@dataclasses.dataclass
class AccumulatedSample:
    """A single pseudo-labeled sample.

    Attributes:
        timestamp: ISO-8601 UTC timestamp of the prediction.
        predicted_class: Predicted class index.
        class_name: Human-readable class name, or None if not available.
        confidence: Confidence score of the predicted class (0-1).
        probabilities: Full probability distribution across all classes.
        model_version: MLflow model version that generated this prediction.
        image_ref: S3 key or file path referencing the source image (placeholder for Phase A).
    """

    timestamp: str
    predicted_class: int
    class_name: str | None
    confidence: float
    probabilities: list[float]
    model_version: str = ""
    image_ref: str = ""

    def to_dict(self) -> dict:
        """Return the sample as a plain dictionary.

        Returns:
            Dictionary representation of this sample.
        """
        return dataclasses.asdict(self)

    def to_json_line(self) -> str:
        """Return the sample as a single JSON line without a trailing newline.

        Returns:
            JSON-serialized string for this sample.
        """
        return json.dumps(self.to_dict())
