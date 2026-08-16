"""Persist local screenshots used for vision calibration and debugging."""

from datetime import datetime
from pathlib import Path


def save_screenshot(png_bytes: bytes) -> Path:
    directory = Path("data/observations/vision")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"table-{stamp}.png"
    path.write_bytes(png_bytes)
    return path
