"""Visible, user-authenticated Gambit table observer and action runner."""

from pathlib import Path
from random import uniform
from time import sleep
from typing import TYPE_CHECKING, Callable
import re
import json
from math import atan2, pi
from datetime import datetime
from dataclasses import dataclass, replace

from src.reader.game_state import parse_visible_state
from src.reader.recorder import ObservationRecorder
from src.strategy.conservative import recommend, with_vision_hand
from src.vision.cards import CardRead

if TYPE_CHECKING:
    from playwright.sync_api import Page


GAMBIT_URL = "https://gambit.com/"
PROFILE_DIRECTORY = Path(".browser-profile")
# Gambit may add an accessible keyboard hint, e.g. "Fold (F)".
FOLD_LABEL = re.compile(r"\bfold\b", re.IGNORECASE)
CALL_LABEL = re.compile(r"^Call:\s*\d+(?:\.\d+)?(?:\s*BB)?$", re.IGNORECASE)
RAISE_LABEL = re.compile(r"^(?:Check\s+)?(?:Bet|Raise):\s*\d+(?:\.\d+)?(?:\s*BB)?$", re.IGNORECASE)
POT_LABEL = re.compile(r"^(\d+(?:\.\d+)?)\s*BB$", re.IGNORECASE)
SIX_MAX_POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
STABLE_DECISION_FRAMES = 2


@dataclass(frozen=True)
class DecisionSnapshot:
    """Immutable facts that must remain unchanged for one poker decision."""

    hero_turn: bool
    hero_cards: tuple[str | None, ...]
    board_cards: tuple[str | None, ...]
    street: str | None
    available_actions: frozenset[str]
    call_amount: float | None
    raise_amount: float | None
    pot_amount: float | None
    hero_stack: float | None
    effective_stack: float | None
    active_players: int | None
    hero_position: str | None
    action_history: tuple[str, ...]

    @property
    def actionable(self) -> bool:
        return self.hero_turn and self.street is not None and bool(self.available_actions)


@dataclass
class StableDecisionSnapshotDetector:
    """Accept a snapshot only after it is identical in consecutive polling frames."""

    required_frames: int = STABLE_DECISION_FRAMES
    candidate: DecisionSnapshot | None = None
    candidate_frames: int = 0

    def __post_init__(self) -> None:
        if self.required_frames < 2:
            raise ValueError("required_frames must be at least two")

    def reset(self) -> None:
        self.candidate = None
        self.candidate_frames = 0

    def observe(self, snapshot: DecisionSnapshot) -> DecisionSnapshot | None:
        if not snapshot.actionable:
            self.reset()
            return None
        if snapshot == self.candidate:
            self.candidate_frames += 1
        else:
            self.candidate = snapshot
            self.candidate_frames = 1
        return snapshot if self.candidate_frames >= self.required_frames else None


def _table_summary(page: "Page") -> str:
    """Return a compact, visible-text snapshot without inspecting browser storage."""
    text = page.locator("body").inner_text(timeout=2_000)
    return " ".join(text.split())[:500]


def _fold_button_is_ready(page: "Page") -> bool:
    """Detect an actionable Fold button using its user-visible accessible name."""
    return _find_fold_control(page) is not None


def _fold(page: "Page") -> bool:
    """Click only the action that was confirmed ready in this UI frame."""
    sleep(uniform(0, 1))
    fold = _find_fold_control(page)
    if fold is None:
        return False
    fold.click(timeout=2_000)
    return True


def _next_hand_if_available(page: "Page") -> bool:
    """Advance only through Gambit's one visible post-hand control."""
    next_hand = _visible_text_control(page, "Next Hand")
    if next_hand is not None:
        sleep(uniform(0, 1))
        # Re-resolve after the pause because the table can update quickly.
        next_hand = _visible_text_control(page, "Next Hand")
        if next_hand is None:
            return False
        next_hand.click(timeout=2_000)
        return True
    return False


def _find_action_control(page: "Page", action: str):
    """Resolve exactly one visible live action control by its displayed label."""
    if action != "RAISE" and _visible_text_control(page, "All-In") is None:
        return None
    label = {
        "CHECK": "Check",
        "FOLD": "Fold",
        "RAISE": RAISE_LABEL,
    }.get(action)
    return _visible_text_control(
        page,
        label if label is not None else CALL_LABEL,
    )


def _live_call_amount(page: "Page") -> float | None:
    """Read the current Call button, never a historical value in page text."""
    control = _find_action_control(page, "CALL")
    if control is None:
        return None
    match = CALL_LABEL.fullmatch(control.inner_text().strip())
    if match is None:
        return None
    amount = re.search(r"\d+(?:\.\d+)?", match.group(0))
    return float(amount.group(0)) if amount is not None else None


def _live_raise_amount(page: "Page") -> float | None:
    """Read the current Raise/Bet button amount, never a sizing preset."""
    control = _find_action_control(page, "RAISE")
    if control is None:
        return None
    match = RAISE_LABEL.fullmatch(control.inner_text().strip())
    if match is None:
        return None
    amount = re.search(r"\d+(?:\.\d+)?", match.group(0))
    return float(amount.group(0)) if amount is not None else None


def _live_pot_amount(page: "Page", layout) -> float | None:
    """Read the standalone pot label geometrically scoped above the board."""
    if not layout.board:
        return None
    left = min(region.x for region in layout.board)
    right = max(region.x + region.width for region in layout.board)
    top = min(region.y for region in layout.board)
    height = max(region.height for region in layout.board)
    labels = page.locator("*").evaluate_all(
        r"""(elements, region) => {
          const width = window.innerWidth, height = window.innerHeight;
          const left = region[0] * width, right = region[1] * width;
          const top = region[2] * height, bandTop = top - region[3] * height * 0.75;
          return elements.map((element) => {
            const text = (element.innerText || '').trim();
            const rect = element.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2, centerY = rect.y + rect.height / 2;
            return {text, area: rect.width * rect.height,
              distance: Math.abs(centerX - (left + right) / 2)};
          }).filter(({text, area, distance}, index) => {
            const element = elements[index];
            const rect = element.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2, centerY = rect.y + rect.height / 2;
            return /^\d+(?:\.\d+)?\s*BB$/i.test(text) && area > 0
              && centerX >= left && centerX <= right && centerY >= bandTop && centerY < top;
          }).sort((first, second) => first.area - second.area || first.distance - second.distance)
            .map(({text}) => text);
        }""",
        [left, right, top, height],
    )
    if not labels:
        return None
    match = POT_LABEL.fullmatch(labels[0])
    return float(match.group(1)) if match is not None else None


def _visible_text_control(page: "Page", text: str | re.Pattern[str]):
    """Choose the innermost visible match from Gambit's nested custom controls."""
    matches = page.get_by_text(text, exact=True).all()
    for candidate in reversed(matches):
        if candidate.is_visible():
            return candidate
    return None


def _visible_dom_map(page: "Page") -> dict[str, object]:
    """Capture visible UI metadata only, for stable selector discovery."""
    extractor = """(elements) => elements.filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
    }).map((element) => ({
      tag: element.tagName.toLowerCase(),
      text: (element.innerText || element.value || '').trim().slice(0, 120),
      role: element.getAttribute('role'),
      ariaLabel: element.getAttribute('aria-label'),
      title: element.getAttribute('title'),
      testId: element.getAttribute('data-testid'),
      disabled: element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true',
      data: Object.fromEntries(Array.from(element.attributes)
        .filter((attribute) => attribute.name.startsWith('data-'))
        .map((attribute) => [attribute.name, attribute.value])),
      rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
    }))"""
    controls = page.locator("button, [role='button'], input[type='button'], input[type='submit']").evaluate_all(extractor)
    cards = page.locator("body").evaluate(
        """(body) => {
          const visible = (element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const description = (element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const source = element.getAttribute('src') || element.getAttribute('srcset') || '';
            const classes = typeof element.className === 'string' ? element.className : '';
            return {
              tag: element.tagName.toLowerCase(), id: element.id || null,
              className: classes || null, role: element.getAttribute('role'),
              alt: element.getAttribute('alt'), ariaLabel: element.getAttribute('aria-label'),
              text: (element.innerText || '').trim().slice(0, 300) || null,
              attributes: Object.fromEntries(Array.from(element.attributes).map((attribute) => [attribute.name, attribute.value])),
              source: source.startsWith('data:') ? 'inline-data-image' : source.slice(0, 500) || null,
              rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
              style: {backgroundImage: style.backgroundImage, backgroundSize: style.backgroundSize,
                backgroundPosition: style.backgroundPosition, transform: style.transform,
                opacity: style.opacity, objectFit: style.objectFit},
              html: element.outerHTML.slice(0, 4000),
              ancestors: Array.from({length: 3}, (_, index) => {
                let parent = element;
                for (let step = 0; step <= index; step += 1) parent = parent?.parentElement;
                return parent ? {tag: parent.tagName.toLowerCase(), id: parent.id || null,
                  className: typeof parent.className === 'string' ? parent.className || null : null,
                  attributes: Object.fromEntries(Array.from(parent.attributes).map((attribute) => [attribute.name, attribute.value])),
                  html: parent.outerHTML.slice(0, 2000)} : null;
              }).filter(Boolean),
            };
          };
          const candidates = new Set();
          body.querySelectorAll("img, svg, canvas, [aria-label*='card' i], [data-card], [class*='card' i], [id*='card' i]")
            .forEach((element) => candidates.add(element));
          return Array.from(candidates).filter(visible).map(description);
        }"""
    )
    tables = page.locator("body").evaluate(
        """(body) => Array.from(body.querySelectorAll("[class*='table' i], [id*='table' i], [data-testid*='table' i]"))
          .filter((element) => { const rect = element.getBoundingClientRect(); return rect.width > 0 && rect.height > 0; })
          .map((element) => ({tag: element.tagName.toLowerCase(), id: element.id || null,
            className: typeof element.className === 'string' ? element.className || null : null,
            attributes: Object.fromEntries(Array.from(element.attributes).map((attribute) => [attribute.name, attribute.value])),
            html: element.outerHTML.slice(0, 12000)}))"""
    )
    action_candidates = page.locator("*").evaluate_all(
        """(elements) => elements.filter((element) => {
          const text = (element.innerText || '').trim();
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0
            && /^(Fold|Check|Next Hand|Call:\\s*\\d+|Raise:\\s*\\d+)$/.test(text);
        }).map((element) => ({
          tag: element.tagName.toLowerCase(), text: element.innerText.trim(),
          className: element.className || null, role: element.getAttribute('role'),
          ariaLabel: element.getAttribute('aria-label'),
          attributes: Object.fromEntries(Array.from(element.attributes)
            .filter((attribute) => attribute.name === 'id' || attribute.name === 'type' || attribute.name.startsWith('data-'))
            .map((attribute) => [attribute.name, attribute.value])),
          parent: {tag: element.parentElement?.tagName.toLowerCase() || null,
            className: element.parentElement?.className || null},
        }))"""
    )
    return {
        "controls": controls,
        "action_candidates": action_candidates,
        "card_candidates": cards,
        "table_candidates": tables,
    }


def inspect_table(interval_seconds: float, target_url: str | None = None) -> None:
    """Save visible table metadata and screenshots without clicking any controls."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    if target_url is not None and not target_url.startswith("https://gambit.com/"):
        raise ValueError("--url must be an https://gambit.com/ URL")
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install -r requirements.txt"
        ) from error

    directory = Path("data/inspections")
    directory.mkdir(parents=True, exist_ok=True)
    PROFILE_DIRECTORY.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIRECTORY.resolve()),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url or GAMBIT_URL, wait_until="domcontentloaded")
        print("Inspector open. Sign in and navigate to a table; no table actions will be taken.")
        previous = ""
        try:
            while True:
                try:
                    visible_text = page.locator("body").inner_text(timeout=2_000)
                    dom = _visible_dom_map(page)
                    fingerprint = json.dumps({"text": visible_text, "dom": dom}, sort_keys=True)
                    if fingerprint != previous:
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                        screenshot_path = directory / f"gambit-{stamp}.png"
                        metadata_path = directory / f"gambit-{stamp}.json"
                        page.screenshot(path=str(screenshot_path))
                        metadata_path.write_text(
                            json.dumps(
                                {
                                    "captured_at": datetime.now().astimezone().isoformat(),
                                    "url": page.url,
                                    "visible_text": visible_text,
                                    "visible_dom": dom,
                                    "screenshot": screenshot_path.name,
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        print(f"INSPECTION: saved {metadata_path}")
                        previous = fingerprint
                except Error as error:
                    print(f"WAIT: {error.__class__.__name__}")
                sleep(interval_seconds)
        except KeyboardInterrupt:
            print("Inspector stopped.")
        finally:
            context.close()


def _apply_action(
    page: "Page",
    action: str,
    expected_snapshot: DecisionSnapshot,
    snapshot_reader: Callable[[], DecisionSnapshot],
) -> bool:
    """Click only if a fresh full snapshot still matches the stable decision."""
    if action not in expected_snapshot.available_actions:
        print(f"ACTION: {action.title()} unavailable — not present in the stable snapshot")
        return False
    sleep(uniform(0, 1))
    current_snapshot = snapshot_reader()
    if current_snapshot != expected_snapshot:
        print(f"ACTION: {action.title()} cancelled — decision snapshot changed")
        return False
    control = _find_action_control(page, action)
    if control is None:
        print(f"ACTION: {action.title()} unavailable — control changed before click")
        return False
    control.click(timeout=2_000)
    print(f"ACTION: {action.title()} clicked")
    return True


def _print_vision_state(
    dom_card_matcher,
    state,
    stage: str | None,
    show_hand_strength: bool,
) -> None:
    print(
        "TURN: "
        f"stage={stage or '?'} "
        f"hero=[{_format_card_reads(state.hero)}] "
        f"board=[{_format_card_reads(state.board)}] "
        f"known={dom_card_matcher.card_count}/52"
    )
    if show_hand_strength:
        from src.strategy.hand_strength import evaluate_hand

        board = tuple(read.card for read in state.board if not read.is_empty)
        strength = evaluate_hand(state.hero_cards, board)
        if strength is not None:
            print(f"HAND: {stage or '?'} | {strength.text}")
        elif stage == "preflop":
            print("HAND: preflop | waiting for the flop")
        else:
            print("HAND: unavailable (cards are not confirmed)")


def _format_card_reads(cards) -> str:
    """Show accepted cards and the best candidate for low-confidence matches."""
    parts = []
    for card in cards:
        label = "empty" if card.is_empty else card.card or f"{card.candidate or '?'}?"
        parts.append(f"{label} {card.confidence:.0%}")
    return ", ".join(parts) or "none"


def _state_summary(state) -> str:
    """Produce a stable terminal summary without dumping all visible page text."""
    call = "?" if state.to_call is None else f"{state.to_call:g} BB"
    stack = "?" if state.hero_stack_bb is None else f"{state.hero_stack_bb:g} BB"
    effective = "?" if state.effective_stack_bb is None else f"{state.effective_stack_bb:g} BB"
    raise_to = "?" if state.current_raise_to_bb is None else f"{state.current_raise_to_bb:g} BB"
    players = "?" if state.active_players is None else str(state.active_players)
    return (
        f"street={state.street or '?'} position={state.hero_position or '?'} "
        f"stack={stack} effective={effective} players={players} call={call} raise_to={raise_to} "
        f"check={'yes' if state.can_check else 'no'}"
    )


def _six_max_position(
    hero: tuple[float, float] | None,
    button: tuple[float, float] | None,
    table_center: tuple[float, float] | None,
    table_bounds: tuple[float, float, float, float] | None = None,
) -> str | None:
    """Map hero's seat to BTN/SB/BB/UTG/HJ/CO using the dealer-button seat."""
    if hero is None or button is None or table_center is None:
        return None

    if table_bounds is not None:
        table_x, table_y, table_width, table_height = table_bounds
        if table_width <= 0 or table_height <= 0:
            return None
        # Clockwise visual seat order on Gambit's flattened six-max table.
        # The dealer chip is rendered inward from its owner, so classifying it
        # against these table-relative anchors is substantially more reliable
        # than treating the layout as six equally spaced points on a circle.
        anchors = (
            (0.50, 0.15),  # top
            (0.91, 0.30),  # upper right
            (0.91, 0.65),  # lower right
            (0.50, 0.86),  # bottom / hero
            (0.09, 0.65),  # lower left
            (0.09, 0.30),  # upper left
        )

        def seat_index(point: tuple[float, float], maximum_distance: float) -> int | None:
            normalized = (
                (point[0] - table_x) / table_width,
                (point[1] - table_y) / table_height,
            )
            distances = sorted(
                (
                    ((normalized[0] - x) ** 2 + (normalized[1] - y) ** 2) ** 0.5,
                    index,
                )
                for index, (x, y) in enumerate(anchors)
            )
            if distances[0][0] > maximum_distance:
                return None
            if distances[1][0] - distances[0][0] < 0.04:
                return None
            return distances[0][1]

        hero_seat = seat_index(hero, maximum_distance=0.20)
        button_seat = seat_index(button, maximum_distance=0.25)
        if hero_seat is None or button_seat is None:
            return None
        return SIX_MAX_POSITIONS[(hero_seat - button_seat) % len(SIX_MAX_POSITIONS)]

    center_x, center_y = table_center
    button_angle = atan2(button[1] - center_y, button[0] - center_x)
    hero_angle = atan2(hero[1] - center_y, hero[0] - center_x)
    clockwise_steps = ((hero_angle - button_angle) % (2 * pi)) / (2 * pi / len(SIX_MAX_POSITIONS))
    nearest_seat = round(clockwise_steps) % len(SIX_MAX_POSITIONS)
    # A geometric match more than a third of a seat away is too uncertain to
    # silently label as a poker position.
    if abs(clockwise_steps - round(clockwise_steps)) > 1 / 3:
        return None
    return SIX_MAX_POSITIONS[nearest_seat]


def _read_six_max_position(page: "Page") -> str | None:
    """Read visible table geometry only; return unknown on an incomplete layout."""
    geometry = page.locator("body").evaluate(
        """(body) => {
          const visible = (element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const center = (element) => {
            if (!element || !visible(element)) return null;
            const rect = element.getBoundingClientRect();
            return [rect.x + rect.width / 2, rect.y + rect.height / 2];
          };
          const images = Array.from(body.querySelectorAll('img'));
          const table = images.find((image) => image.getAttribute('src')?.includes('/poker/table/'));
          const button = images.find((image) => image.getAttribute('src')?.includes('dealer-button'));
          const action = Array.from(body.querySelectorAll('*'))
            .filter((element) => (element.innerText || '').trim() === 'ACTION' && visible(element))
            .sort((first, second) => {
              const firstRect = first.getBoundingClientRect(), secondRect = second.getBoundingClientRect();
              return firstRect.width * firstRect.height - secondRect.width * secondRect.height;
            })[0];
           const tableRect = table?.getBoundingClientRect();
           return {table: center(table), button: center(button), hero: center(action),
             tableBounds: tableRect ? [tableRect.x, tableRect.y, tableRect.width, tableRect.height] : null};
        }"""
    )
    return _six_max_position(
        tuple(geometry["hero"]) if geometry["hero"] is not None else None,
        tuple(geometry["button"]) if geometry["button"] is not None else None,
        tuple(geometry["table"]) if geometry["table"] is not None else None,
        tuple(geometry["tableBounds"]) if geometry["tableBounds"] is not None else None,
    )


def _board_needs_screenshot_fallback(sources: tuple[str | None, ...]) -> bool:
    """Use a screenshot only for an ambiguous DOM board layout.

    A dealt flop or turn has a contiguous run of SVG sources.  Missing sources
    after that run are ordinary undealt slots, not unknown cards.  Treating
    those trailing slots as screenshot reads can turn table background into a
    low-confidence card candidate and unnecessarily prompt for a label.
    """
    dealt_indices = [index for index, source in enumerate(sources) if source is not None]
    if not dealt_indices:
        # With no DOM board card, retain screenshot validation in case a layout
        # change made every board region miss its card face.
        return True
    last_dealt = dealt_indices[-1]
    return any(source is None for source in sources[:last_dealt + 1])


def _read_dom_board(dom_card_matcher, sources: tuple[str | None, ...], screenshot_state=None) -> tuple[CardRead, ...]:
    """Read DOM board faces and mark known trailing empty slots explicitly."""
    return tuple(
        dom_card_matcher.read(source) if source is not None
        else (
            screenshot_state.board[index]
            if screenshot_state is not None
            else CardRead(card=None, confidence=1.0, is_empty=True)
        )
        for index, source in enumerate(sources)
    )


def _available_actions(page: "Page") -> frozenset[str]:
    """Return the complete set of live actions visible in this UI frame."""
    return frozenset(
        action
        for action in ("FOLD", "CHECK", "CALL", "RAISE")
        if _find_action_control(page, action) is not None
    )


def _decision_snapshot(
    page: "Page",
    hero_turn: bool,
    vision_state,
    street: str | None,
    layout,
    raw_text: str | None = None,
    hero_position: str | None = None,
) -> DecisionSnapshot:
    """Freeze all card and action facts used by a decision."""
    raw_text = raw_text if raw_text is not None else page.locator("body").inner_text(timeout=2_000)
    parsed = parse_visible_state(raw_text, read_coaching_hand=False)
    actions = _available_actions(page)
    return DecisionSnapshot(
        hero_turn=hero_turn,
        hero_cards=vision_state.hero_cards,
        board_cards=tuple(read.card for read in vision_state.board if not read.is_empty),
        street=street,
        available_actions=actions,
        call_amount=_live_call_amount(page) if "CALL" in actions else None,
        raise_amount=_live_raise_amount(page) if "RAISE" in actions else None,
        pot_amount=_live_pot_amount(page, layout) or parsed.pot_bb,
        hero_stack=parsed.hero_stack_bb,
        effective_stack=parsed.effective_stack_bb,
        active_players=parsed.active_players,
        hero_position=hero_position,
        action_history=parsed.action_history,
    )


def _read_live_decision_snapshot(page: "Page", vision_reader, dom_card_matcher) -> DecisionSnapshot:
    """Re-read the complete live state independently for pre-click validation."""
    from src.vision.dom_cards import board_card_sources, hero_card_sources
    from src.vision.reader import VisionState
    from src.vision.stage import stage_from_board

    hero_sources = hero_card_sources(page, vision_reader.layout)
    board_sources = board_card_sources(page, vision_reader.layout)
    hero_turn = _is_hero_turn_dom(page, vision_reader.layout)
    has_dom_hero_cards = bool(hero_sources) and all(source is not None for source in hero_sources)
    if has_dom_hero_cards:
        screenshot_state = None
        if hero_turn and _board_needs_screenshot_fallback(board_sources):
            screenshot_state = vision_reader.read_screenshot(page.screenshot())
        vision_state = VisionState(
            hero=tuple(dom_card_matcher.read(source) for source in hero_sources),
            board=_read_dom_board(dom_card_matcher, board_sources, screenshot_state),
        )
    else:
        vision_state = vision_reader.read_screenshot(page.screenshot())
    raw_text = page.locator("body").inner_text(timeout=2_000)
    hero_position = _read_six_max_position(page) if hero_turn else None
    return _decision_snapshot(
        page,
        hero_turn,
        vision_state,
        stage_from_board(vision_state.board),
        vision_reader.layout,
        raw_text,
        hero_position,
    )


def _flush_draw_call_reason(
    street: str | None,
    nut_flush_draw: bool,
    to_call: float | None,
    pot_bb: float | None,
    big_blind: float | None,
) -> str | None:
    """Return a conservative draw-call reason only when pricing is known to fit."""
    if to_call is None:
        return None
    from src.strategy.hand_strength import flush_draw_equity

    quality = "Nut flush draw" if nut_flush_draw else "Flush draw"
    equity = flush_draw_equity(street, nut_flush_draw)
    if pot_bb is not None and pot_bb > 0 and equity is not None:
        required_equity = to_call / (pot_bb + to_call)
        if required_equity <= equity:
            return f"{quality}; pot odds require {required_equity:.0%} versus {equity:.0%} draw equity"
        return None
    if big_blind is not None and to_call <= 2 * big_blind:
        return f"{quality}; pot is unknown and call is at most 2 big blinds"
    return None


def _find_fold_control(page: "Page"):
    """Find one visible interactive Fold control, never plain table-history text."""
    candidates = (
        page.get_by_role("button", name=FOLD_LABEL),
        page.locator("button").filter(has_text=FOLD_LABEL),
        page.locator("[role='button']").filter(has_text=FOLD_LABEL),
    )
    for candidate in candidates:
        if candidate.count() == 1 and candidate.is_visible() and candidate.is_enabled():
            return candidate

    # Gambit's table currently renders its action controls with a custom
    # clickable element, without a button tag or ARIA role. Restrict this text
    # fallback to the live action panel: historical actions use uppercase FOLD
    # and the panel disappears after the hand resolves.
    live_action_panel = _visible_text_control(page, "All-In")
    text_control = _visible_text_control(page, "Fold")
    if live_action_panel is not None and text_control is not None:
        return text_control
    return None


def _print_state(
    page: "Page",
    previous: str,
    strategy: str,
    recorder: ObservationRecorder | None,
    record_dom: bool,
    hero_turn: bool,
    hero_position: str | None,
) -> str:
    raw_text = page.locator("body").inner_text(timeout=2_000)
    summary = " ".join(raw_text.split())[:500]
    if summary != previous:
        state = replace(parse_visible_state(raw_text), hero_position=hero_position)
        print(f"STATE: {_state_summary(state)} hero_turn={'yes' if hero_turn else 'no'}")
        if strategy == "conservative" or recorder is not None:
            if recorder is not None:
                recorder.write(
                    raw_text,
                    state,
                    hero_turn=hero_turn,
                    dom_map=_visible_dom_map(page) if record_dom else None,
                )
    return summary


def _is_hero_turn_dom(page: "Page", layout) -> bool:
    """Locate the visible ACTION label inside the calibrated hero action region."""
    return bool(page.locator("*").evaluate_all(
        """(elements, region) => {
          const width = window.innerWidth, height = window.innerHeight;
          const target = {x: region[0] * width, y: region[1] * height,
            width: region[2] * width, height: region[3] * height};
          return elements.some((element) => {
            if ((element.innerText || '').trim() !== 'ACTION') return false;
            const rect = element.getBoundingClientRect();
            return rect.x < target.x + target.width && rect.x + rect.width > target.x
              && rect.y < target.y + target.height && rect.y + rect.height > target.y;
          });
        }""",
        [layout.action_badge.x, layout.action_badge.y, layout.action_badge.width, layout.action_badge.height],
    ))


def _observe_once(
    page: "Page",
    auto_fold: bool,
    fold_was_ready: bool,
    waiting_for_next_hand: bool,
) -> tuple[bool, bool]:
    """Run one polling cycle and return Fold and post-fold state.

    The transition guard prevents repeated clicks against the same turn while a
    slow page is still rendering its result.
    """
    if waiting_for_next_hand and _next_hand_if_available(page):
        print("ACTION: Next Hand clicked")
        return False, False
    if waiting_for_next_hand:
        # The action panel remains visible while other players finish the hand.
        # Do not inspect it again until our post-fold Next Hand control appears.
        return False, True

    fold_is_ready = _fold_button_is_ready(page)
    if auto_fold and fold_is_ready and not fold_was_ready:
        if _fold(page):
            print("ACTION: Fold clicked")
            return False, True
        print("WAIT: Fold control changed before click")
        return False, False
    return fold_is_ready, waiting_for_next_hand


def observe_table(
    auto_fold: bool,
    interval_seconds: float,
    target_url: str | None = None,
    strategy: str = "fold-only",
    record: bool = False,
    auto_play: bool = False,
    record_dom: bool = False,
    vision: bool = False,
    hand_strength: bool = False,
) -> None:
    """Open a headed browser and print state changes until Ctrl+C is pressed."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    if target_url is not None and not target_url.startswith("https://gambit.com/"):
        raise ValueError("--url must be an https://gambit.com/ URL")

    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install -r requirements.txt"
        ) from error

    vision_reader = None
    dom_card_matcher = None
    if vision or auto_play:
        from src.vision.layout import load_layout
        from src.vision.reader import VisionReader, VisionState

        layout = load_layout()
        if layout is None:
            raise RuntimeError(
                "Vision needs config/vision.json. Copy config/vision.example.json and calibrate it first."
            )
        vision_reader = VisionReader(layout)
        from src.vision.dom_cards import DomCardMatcher
        dom_card_matcher = DomCardMatcher()
        from src.vision.stage import StableStageDetector
        stage_detector = StableStageDetector()
        decision_snapshot_detector = StableDecisionSnapshotDetector()
        prompted_unknown_cards: set[str] = set()

    PROFILE_DIRECTORY.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIRECTORY.resolve()),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url or GAMBIT_URL, wait_until="domcontentloaded")
        print("Browser open. Sign in manually, navigate to your table, then watch this terminal.")
        recorder = ObservationRecorder() if record else None
        if recorder is not None:
            print(f"Recording visible state changes to: {recorder.path}")

        previous = ""
        auto_turn_active = False
        vision_turn_active = False
        vision_reported_stage: str | None = None
        decision_reported_snapshot: DecisionSnapshot | None = None
        between_hands = False
        fold_was_ready = False
        waiting_for_next_hand = False
        try:
            while True:
                try:
                    hero_turn = False
                    vision_state = None
                    stage = None
                    if vision_reader is not None:
                        from src.vision.dom_cards import board_card_sources, hero_card_sources
                        hero_sources = hero_card_sources(page, vision_reader.layout)
                        board_sources = board_card_sources(page, vision_reader.layout)
                        has_dom_hero_cards = bool(hero_sources) and all(source is not None for source in hero_sources)
                        hero_turn = _is_hero_turn_dom(page, vision_reader.layout)
                        screenshot = None
                        screenshot_state = None
                        if has_dom_hero_cards:
                            hero_reads = tuple(dom_card_matcher.read(source) for source in hero_sources)
                            # A hole in the dealt DOM-card sequence can mean that
                            # calibration missed a card. Trailing absent slots are
                            # expected on preflop, flop, and turn and are recorded
                            # as empty without screenshot matching.
                            if hero_turn and _board_needs_screenshot_fallback(board_sources):
                                screenshot = page.screenshot()
                                screenshot_state = vision_reader.read_screenshot(screenshot)
                            board_reads = _read_dom_board(dom_card_matcher, board_sources, screenshot_state)
                            vision_state = VisionState(hero=hero_reads, board=board_reads)
                        else:
                            screenshot = page.screenshot()
                            vision_state = vision_reader.read_screenshot(screenshot)
                        stage = stage_detector.observe(vision_state.board)
                        if vision and hero_turn:
                            from src.vision.training import prompt_for_unknown_cards, prompt_for_unknown_dom_cards
                            saved_dom_cards = prompt_for_unknown_dom_cards(
                                hero_sources,
                                dom_card_matcher,
                                prompted_unknown_cards,
                                locations=("hero-1", "hero-2"),
                            ) + prompt_for_unknown_dom_cards(
                                board_sources,
                                dom_card_matcher,
                                prompted_unknown_cards,
                                locations=("board-1", "board-2", "board-3", "board-4", "board-5"),
                            )
                            screenshot_skip_locations = (
                                frozenset({"hero-1", "hero-2"})
                                | frozenset(
                                    f"board-{index + 1}"
                                    for index, source in enumerate(board_sources)
                                    if source is not None
                                )
                                if has_dom_hero_cards
                                else frozenset()
                            )
                            saved_screenshot_cards = 0 if screenshot is None else prompt_for_unknown_cards(
                                screenshot,
                                vision_reader,
                                vision_state,
                                prompted_unknown_cards,
                                skip_locations=screenshot_skip_locations,
                            )
                            if saved_dom_cards or saved_screenshot_cards:
                                if has_dom_hero_cards:
                                    if screenshot is not None:
                                        screenshot_state = vision_reader.read_screenshot(screenshot)
                                    vision_state = replace(
                                        vision_state,
                                        hero=tuple(dom_card_matcher.read(source) for source in hero_sources),
                                        board=_read_dom_board(dom_card_matcher, board_sources, screenshot_state),
                                    )
                                elif screenshot is not None:
                                    vision_state = vision_reader.read_screenshot(screenshot)
                                stage = stage_detector.observe(vision_state.board)
                    hero_position = _read_six_max_position(page) if hero_turn else None
                    previous = _print_state(page, previous, strategy, recorder, record_dom, hero_turn, hero_position)
                    next_hand_visible = _visible_text_control(page, "Next Hand") is not None
                    if next_hand_visible and not between_hands:
                        if vision_reader is not None:
                            stage_detector.reset()
                        auto_turn_active = False
                        vision_turn_active = False
                        vision_reported_stage = None
                        decision_reported_snapshot = None
                        decision_snapshot_detector.reset()
                        if vision_reader is not None:
                            prompted_unknown_cards.clear()
                        between_hands = True
                    elif not next_hand_visible:
                        between_hands = False
                    if auto_play and _next_hand_if_available(page):
                        print("ACTION: Next Hand clicked")
                        auto_turn_active = False
                        vision_turn_active = False
                        vision_reported_stage = None
                        decision_reported_snapshot = None
                        decision_snapshot_detector.reset()
                        sleep(interval_seconds)
                        continue
                    raw_text = page.locator("body").inner_text(timeout=2_000)
                    stable_snapshot = None
                    if vision_state is not None:
                        current_snapshot = _decision_snapshot(
                            page,
                            hero_turn,
                            vision_state,
                            stage,
                            vision_reader.layout,
                            raw_text,
                            hero_position,
                        )
                        stable_snapshot = decision_snapshot_detector.observe(current_snapshot)
                    if (
                        vision
                        and hero_turn
                        and (not vision_turn_active or stage != vision_reported_stage)
                    ):
                        _print_vision_state(
                            dom_card_matcher,
                            vision_state,
                            stage,
                            hand_strength,
                        )
                        vision_turn_active = True
                        vision_reported_stage = stage
                    if not hero_turn:
                        vision_turn_active = False
                        vision_reported_stage = None
                    if (
                        vision
                        and stable_snapshot is not None
                        and stable_snapshot != decision_reported_snapshot
                    ):
                        from src.strategy.conservative import Recommendation
                        from src.strategy.hand_strength import evaluate_hand

                        board = stable_snapshot.board_cards
                        strength = evaluate_hand(stable_snapshot.hero_cards, board)
                        decision_state = with_vision_hand(
                            parse_visible_state(raw_text, read_coaching_hand=False),
                            stable_snapshot.hero_cards,
                            stable_snapshot.board_cards,
                        )
                        decision_state = replace(
                            decision_state,
                            street=stable_snapshot.street,
                            hero_position=stable_snapshot.hero_position,
                            can_check="CHECK" in stable_snapshot.available_actions,
                            to_call=stable_snapshot.call_amount,
                            pot_bb=stable_snapshot.pot_amount,
                            hero_stack_bb=stable_snapshot.hero_stack,
                            effective_stack_bb=stable_snapshot.effective_stack,
                            active_players=stable_snapshot.active_players,
                            action_history=stable_snapshot.action_history,
                        )
                        decision = recommend(decision_state)
                        if stable_snapshot.street in {"flop", "turn", "river"}:
                            has_made_hand = strength is not None and strength.score[0] >= 1
                            if decision_state.can_check:
                                decision = Recommendation(
                                    "RAISE" if has_made_hand else "CHECK",
                                    strength.text if has_made_hand else "No made hand; check for free",
                                )
                        position = decision_state.hero_position or "?"
                        stack = "?" if decision_state.hero_stack_bb is None else f"{decision_state.hero_stack_bb:g} BB"
                        print(f"DECISION: {decision.action} — {decision.reason} [position={position} stack={stack}]")
                        decision_reported_snapshot = stable_snapshot
                        if auto_play and decision.action in {"FOLD", "CHECK", "CALL", "RAISE"}:
                            auto_turn_active = _apply_action(
                                page,
                                decision.action,
                                stable_snapshot,
                                lambda: _read_live_decision_snapshot(
                                    page, vision_reader, dom_card_matcher
                                ),
                            )
                            decision_snapshot_detector.reset()
                            if not auto_turn_active:
                                # A cancelled action must earn two fresh stable
                                # frames before it may be attempted again.
                                decision_reported_snapshot = None
                    if not hero_turn:
                        auto_turn_active = False
                        decision_reported_snapshot = None
                    fold_was_ready, waiting_for_next_hand = _observe_once(
                        page,
                        auto_fold,
                        fold_was_ready,
                        waiting_for_next_hand,
                    )
                except Error as error:
                    # Tables can briefly re-render between polls; keep observing.
                    print(f"WAIT: {error.__class__.__name__}")
                    fold_was_ready = False
                sleep(interval_seconds)
        except KeyboardInterrupt:
            print("Observer stopped.")
        finally:
            context.close()
