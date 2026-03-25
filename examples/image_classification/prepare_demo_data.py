"""Prepare demo dataset for the image classification pipeline.

Downloads a small subset of CIFAR-10 and organizes it into the expected
directory structure for the MLOps pipeline:

    data/raw/cifar10-demo/
    ├── train/
    │   ├── airplane/
    │   ├── automobile/
    │   └── ...
    └── val/
        ├── airplane/
        ├── automobile/
        └── ...

Usage:
    python examples/image_classification/prepare_demo_data.py
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from torchvision.datasets import CIFAR10

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CIFAR10_CLASSES = [
    "airplane",
    "automobile",
    "bird",
    "cat",
    "deer",
    "dog",
    "frog",
    "horse",
    "ship",
    "truck",
]

# Limit dataset size for demo purposes
TRAIN_PER_CLASS = 100
VAL_PER_CLASS = 20


def prepare_demo_dataset(output_dir: str | Path = "data/raw/cifar10-demo") -> Path:
    """Download CIFAR-10 and create directory-based dataset.

    Args:
        output_dir: Where to save the organized dataset.

    Returns:
        Path to the created dataset directory.
    """
    output_dir = Path(output_dir)
    if output_dir.exists():
        logger.info("Dataset already exists at %s. Skipping.", output_dir)
        return output_dir

    logger.info("Downloading CIFAR-10...")
    try:
        train_dataset = CIFAR10(root="/tmp/cifar10", train=True, download=True)
        val_dataset = CIFAR10(root="/tmp/cifar10", train=False, download=True)
    except (OSError, RuntimeError) as e:
        raise RuntimeError(
            f"Failed to download CIFAR-10: {e}. "
            "Check your internet connection. If behind a proxy, set HTTP_PROXY/HTTPS_PROXY."
        ) from e

    try:
        _save_subset(train_dataset, output_dir / "train", TRAIN_PER_CLASS)
        _save_subset(val_dataset, output_dir / "val", VAL_PER_CLASS)
    except Exception:
        # Clean up partial writes to avoid corrupt dataset on next run
        import shutil

        if output_dir.exists():
            shutil.rmtree(output_dir)
            logger.error("Cleaned up partial dataset at %s", output_dir)
        raise

    total = (TRAIN_PER_CLASS + VAL_PER_CLASS) * len(CIFAR10_CLASSES)
    logger.info("Demo dataset created: %d images at %s", total, output_dir)

    return output_dir


def _save_subset(
    dataset: CIFAR10,
    split_dir: Path,
    per_class: int,
) -> None:
    """Save a limited number of images per class to disk."""
    class_counts: dict[int, int] = {}

    for img, label in dataset:
        count = class_counts.get(label, 0)
        if count >= per_class:
            continue

        class_name = CIFAR10_CLASSES[label]
        class_dir = split_dir / class_name
        class_dir.mkdir(parents=True, exist_ok=True)

        img_path = class_dir / f"{class_name}_{count:04d}.png"
        if not isinstance(img, Image.Image):
            raise TypeError(f"Expected PIL Image, got {type(img)} at index {count}")
        img.save(img_path)

        class_counts[label] = count + 1

        if all(class_counts.get(i, 0) >= per_class for i in range(len(CIFAR10_CLASSES))):
            break


if __name__ == "__main__":
    try:
        path = prepare_demo_dataset()
        logger.info("Done. Dataset at: %s", path)
    except Exception as e:
        logger.error("Failed to prepare demo dataset: %s", e)
        raise SystemExit(1) from e
