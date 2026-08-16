"""Detect Gambit's blue ACTION badge in the calibrated hero-card region."""

from io import BytesIO

import numpy as np
from PIL import Image

from src.vision.layout import Region, TableLayout


def _crop(image: Image.Image, region: Region) -> Image.Image:
    width, height = image.size
    return image.crop((
        int(region.x * width), int(region.y * height),
        int((region.x + region.width) * width), int((region.y + region.height) * height),
    ))


def is_hero_turn(screenshot: bytes, layout: TableLayout) -> bool:
    """Return true only when the badge's distinctive blue occupies the hero region."""
    pixels = np.asarray(_crop(Image.open(BytesIO(screenshot)).convert("RGB"), layout.action_badge))
    blue = (pixels[:, :, 0] < 30) & (pixels[:, :, 1] > 120) & (pixels[:, :, 1] < 190) & (pixels[:, :, 2] > 180)
    return float(blue.mean()) >= 0.10
