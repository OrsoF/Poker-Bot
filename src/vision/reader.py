"""Capture a browser table screenshot and recognize configured card regions."""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from src.vision.cards import CardRead, CardTemplateMatcher
from src.vision.layout import Region, TableLayout


@dataclass(frozen=True)
class VisionState:
    hero: tuple[CardRead, ...]
    board: tuple[CardRead, ...]

    @property
    def hero_cards(self) -> tuple[str | None, ...]:
        return tuple(read.card for read in self.hero)


def _crop(image: Image.Image, region: Region) -> Image.Image:
    width, height = image.size
    left = int(region.x * width)
    top = int(region.y * height)
    right = int((region.x + region.width) * width)
    bottom = int((region.y + region.height) * height)
    return image.crop((left, top, right, bottom))


class VisionReader:
    def __init__(self, layout: TableLayout, matcher: CardTemplateMatcher | None = None) -> None:
        self.layout = layout
        self.matcher = matcher or CardTemplateMatcher()

    def read_screenshot(self, screenshot: bytes) -> VisionState:
        image = Image.open(BytesIO(screenshot))
        return VisionState(
            hero=tuple(self.matcher.read(_crop(image, region)) for region in self.layout.hero),
            board=tuple(
                self.matcher.read(_crop(image, region), allow_empty=True)
                for region in self.layout.board
            ),
        )

    def card_crops(self, screenshot: bytes) -> dict[str, Image.Image]:
        """Return labelled hero and board crops for interactive template training."""
        image = Image.open(BytesIO(screenshot))
        return {
            **{f"hero-{index + 1}": _crop(image, region) for index, region in enumerate(self.layout.hero)},
            **{f"board-{index + 1}": _crop(image, region) for index, region in enumerate(self.layout.board)},
        }
