"""Interactive collection of card templates during visible observation."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re

from PIL import Image

from src.vision.reader import VisionReader, VisionState
from src.vision.dom_cards import DomCardMatcher, svg_fingerprint


CARD_LABEL = re.compile(r"^(?:[2-9TJQKA])[shdc]$", re.IGNORECASE)
CONFIRMATION_CONFIDENCE = 0.99


def normalize_card_label(value: str) -> str | None:
    """Accept familiar card labels such as `10c` and return canonical `Tc`."""
    label = value.strip().replace(" ", "")
    if label[:2] == "10":
        label = "T" + label[2:]
    if not CARD_LABEL.fullmatch(label):
        return None
    return label[0].upper() + label[1].lower()


def prompt_for_unknown_cards(
    screenshot: bytes,
    reader: VisionReader,
    state: VisionState,
    prompted: set[str],
    templates_directory: Path = Path("data/card_templates"),
    skip_locations: frozenset[str] = frozenset(),
) -> int:
    """Ask once per unseen crop to label unknown cards or verify uncertain reads."""
    crops = reader.card_crops(screenshot)
    reads = {
        **{f"hero-{index + 1}": read for index, read in enumerate(state.hero)},
        **{f"board-{index + 1}": read for index, read in enumerate(state.board)},
    }
    saved = 0
    for location, read in reads.items():
        if location in skip_locations:
            continue
        if read.is_empty or (read.card is not None and read.confidence >= CONFIRMATION_CONFIDENCE):
            continue
        crop = crops[location]
        fingerprint = sha256(crop.tobytes()).hexdigest()
        if fingerprint in prompted:
            continue
        prompted.add(fingerprint)
        guess = read.card or read.candidate or "unknown"
        correction_prompt = read.card is not None
        try:
            message = (
                f"CARD CONFIRM: {location} looks like {guess} ({read.confidence:.0%}). "
                "Press Enter to accept, or enter the correct label: "
                if correction_prompt
                else f"CARD INPUT: {location} is {guess}? ({read.confidence:.0%}). "
                "Enter card label (e.g. Tc), or press Enter to skip: "
            )
            answer = input(message)
        except EOFError:
            return saved
        label = normalize_card_label(answer)
        if not answer.strip():
            print(f"CARD CONFIRM: accepted {guess}" if correction_prompt else f"CARD INPUT: skipped {location}")
            continue
        if label is None:
            print("CARD INPUT: invalid label; use 2-9, T, J, Q, K, or A plus s/h/d/c.")
            continue
        templates_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = templates_directory / f"{label}--manual-{stamp}-{location}.png"
        crop.save(path)
        reader.matcher.templates.append((label, crop.copy()))
        print(f"CARD INPUT: saved {label} -> {path}")
        saved += 1
    return saved


def prompt_for_unknown_dom_cards(
    sources: tuple[str | None, ...],
    matcher: DomCardMatcher,
    prompted: set[str],
    locations: tuple[str, ...] | None = None,
) -> int:
    """Ask for a label once for each visible hero-card SVG face not in the library."""
    saved = 0
    locations = locations or tuple(f"hero-{index}" for index in range(1, len(sources) + 1))
    for index, (source, location) in enumerate(zip(sources, locations), 1):
        if source is None or matcher.read(source).card is not None:
            continue
        fingerprint = svg_fingerprint(source)
        if fingerprint in prompted:
            continue
        prompted.add(fingerprint)
        try:
            answer = input(f"CARD INPUT: {location} is a new card. Enter label (e.g. Tc), or press Enter to skip: ")
        except EOFError:
            return saved
        label = normalize_card_label(answer)
        if not answer.strip():
            print(f"CARD INPUT: skipped {location}")
            continue
        if label is None:
            print("CARD INPUT: invalid label; use 2-9, T, J, Q, K, or A plus s/h/d/c.")
            continue
        matcher.add(label, source)
        print(f"CARD INPUT: saved {label} as a DOM card template")
        saved += 1
    return saved
