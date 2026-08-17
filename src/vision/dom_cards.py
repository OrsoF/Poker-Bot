"""Read Gambit's visible hero-card SVG faces without relying on screenshots."""

from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import unquote

from src.vision.cards import CardRead
from src.vision.layout import TableLayout


TEMPLATES_PATH = Path("data/card_templates/dom_cards.json")


class DomCardMatcher:
    """Map normalized inline SVG card faces to user-confirmed card labels."""

    def __init__(self, path: Path = TEMPLATES_PATH) -> None:
        self.path = path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            payload = {"fingerprints": {}}
        self.fingerprints: dict[str, str] = payload.get("fingerprints", {})

    @property
    def card_count(self) -> int:
        return len(set(self.fingerprints.values()))

    def read(self, source: str | None) -> CardRead:
        if source is None:
            return CardRead(card=None, confidence=0.0, candidate=None)
        card = self.fingerprints.get(svg_fingerprint(source))
        return CardRead(card=card, confidence=1.0 if card is not None else 0.0, candidate=card)

    def add(self, card: str, source: str) -> None:
        self.fingerprints[svg_fingerprint(source)] = card
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"fingerprints": self.fingerprints}, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def card_sources(page, regions) -> tuple[str | None, ...]:
    """Return inline-SVG front images overlapping normalized card regions."""
    faces = page.locator("img").evaluate_all(
        """(images, hero) => {
          const width = window.innerWidth;
          const height = window.innerHeight;
          const overlap = (first, second) => {
            const left = Math.max(first.x, second.x);
            const top = Math.max(first.y, second.y);
            const right = Math.min(first.x + first.width, second.x + second.width);
            const bottom = Math.min(first.y + first.height, second.y + second.height);
            return Math.max(0, right - left) * Math.max(0, bottom - top);
          };
          const candidates = images.map((image) => ({
            source: image.getAttribute('src'), rect: image.getBoundingClientRect(),
          })).filter((image) => image.source?.startsWith('data:image/svg+xml,'));
          return hero.map(([x, y, cardWidth, cardHeight]) => {
            const target = {x: x * width, y: y * height, width: cardWidth * width, height: cardHeight * height};
            const match = candidates.map((candidate) => ({candidate, overlap: overlap(candidate.rect, target)}))
              .filter(({overlap}) => overlap > 0)
              .sort((first, second) => second.overlap - first.overlap)[0];
            return match?.candidate.source || null;
          });
        }""",
        [[region.x, region.y, region.width, region.height] for region in regions],
    )
    return tuple(faces)


def hero_card_sources(page, layout: TableLayout) -> tuple[str | None, ...]:
    return card_sources(page, layout.hero)


def board_card_sources(page, layout: TableLayout) -> tuple[str | None, ...]:
    return card_sources(page, layout.board)


def svg_fingerprint(source: str) -> str:
    """Ignore generated SVG identifiers while preserving the card artwork paths."""
    svg = unquote(source.partition(",")[2])
    svg = re.sub(r'id="[^"]+"', 'id="ID"', svg)
    svg = re.sub(r'url\(#[^)]+\)', 'url(#ID)', svg)
    svg = re.sub(r'href="#[^"]+"', 'href="#ID"', svg)
    return sha256(svg.encode("utf-8")).hexdigest()
