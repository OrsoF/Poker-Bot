"""Template matcher for complete card-face crops named e.g. `As.png`, `Td.png`."""

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageChops


@dataclass(frozen=True)
class CardRead:
    """A template-match result, including the best candidate when it is uncertain."""

    card: str | None
    confidence: float
    candidate: str | None = None
    is_empty: bool = False


def _difference_score(card_image: Image.Image, template: Image.Image) -> float:
    candidate = card_image.convert("RGB").resize(template.size)
    difference = ImageChops.difference(candidate, template.convert("RGB"))
    pixels = np.asarray(difference, dtype=np.float32)
    return 1.0 - float(pixels.mean() / 255.0)


class CardTemplateMatcher:
    def __init__(self, templates_directory: Path = Path("data/card_templates")) -> None:
        self.templates: list[tuple[str, Image.Image]] = []
        for template in templates_directory.glob("*.png"):
            match = re.fullmatch(r"([2-9TJQKA][shdc])(?:--.+)?", template.stem)
            if match is not None:
                self.templates.append((match.group(1), Image.open(template).copy()))

    @property
    def template_count(self) -> int:
        return len(self.templates)

    @property
    def card_count(self) -> int:
        return len({card for card, _ in self.templates})

    def read(
        self,
        crop: Image.Image,
        minimum_confidence: float = 0.92,
        allow_empty: bool = False,
    ) -> CardRead:
        if allow_empty and _is_empty_slot(crop):
            return CardRead(card=None, confidence=1.0, candidate=None, is_empty=True)
        if not self.templates:
            return CardRead(card=None, confidence=0.0, candidate=None)
        card, confidence = max(
            ((name, _difference_score(crop, image)) for name, image in self.templates),
            key=lambda item: item[1],
        )
        return CardRead(
            card=card if confidence >= minimum_confidence else None,
            confidence=confidence,
            candidate=card,
        )


def _is_empty_slot(crop: Image.Image) -> bool:
    """Empty board slots are green; dealt cards contain a substantial white face."""
    pixels = np.asarray(crop.convert("RGB"), dtype=np.uint8)
    white_pixels = np.all(pixels >= 200, axis=2)
    return float(white_pixels.mean()) < 0.02
