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
        image_ref: S3 key referencing the source image in object storage.
        image_bytes: Transient field holding raw image data for S3 upload.
            Not serialized to JSON — consumed by AutoAccumulator.add().
    """

    timestamp: str
    predicted_class: int
    class_name: str | None
    confidence: float
    probabilities: list[float]
    model_version: str = ""
    image_ref: str = ""
    image_bytes: bytes | None = dataclasses.field(default=None, repr=False)

    def to_dict(self) -> dict:
        """Return the sample as a plain dictionary (excludes transient fields).

        Returns:
            Dictionary representation of this sample.
        """
        d = dataclasses.asdict(self)
        d.pop("image_bytes", None)
        return d

    def to_json_line(self) -> str:
        """Return the sample as a single JSON line without a trailing newline.

        Returns:
            JSON-serialized string for this sample.
        """
        return json.dumps(self.to_dict())
