"""Load normalized hero-card and board-card locations for the visible table."""

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class TableLayout:
    hero: tuple[Region, ...]
    board: tuple[Region, ...]
    action_badge: Region


def load_layout(path: Path = Path("config/vision.json")) -> TableLayout | None:
    """Return no layout until the user has calibrated their visible table."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))

    def regions(name: str) -> tuple[Region, ...]:
        return tuple(Region(*item) for item in payload.get(name, []))

    return TableLayout(hero=regions("hero"), board=regions("board"), action_badge=Region(*payload["action_badge"]))
