"""Merge visible Gambit reads into immutable table state and source evidence."""

from dataclasses import dataclass, field, replace
from math import atan2, pi
from typing import TYPE_CHECKING

from src.browser.gambit_controls import (
    available_actions,
    live_call_amount,
    live_pot_amount,
    live_raise_amount,
)
from src.models import ObservedState
from src.reader.game_state import parse_visible_state, with_vision_hand
from src.vision.cards import CardRead

if TYPE_CHECKING:
    from playwright.sync_api import Page


SIX_MAX_POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
PREFLOP_ACTION_ORDER = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
STABLE_DECISION_FRAMES = 2


@dataclass(frozen=True, eq=False)
class TableObservation:
    """Merged state plus raw evidence for stability, display, and training.

    parsed_state is the text-only input retained for the existing audit output;
    state is the sole merged input consumed by strategy.
    """

    hero_turn: bool
    state: ObservedState
    raw_text: str = field(compare=False, repr=False)
    parsed_state: ObservedState = field(compare=False, repr=False)
    hero_reads: tuple[CardRead, ...] = field(compare=False, repr=False)
    board_reads: tuple[CardRead, ...] = field(compare=False, repr=False)
    hero_sources: tuple[str | None, ...] = field(compare=False, repr=False)
    board_sources: tuple[str | None, ...] = field(compare=False, repr=False)
    screenshot: bytes | None = field(compare=False, repr=False)

    @property
    def hero_cards(self) -> tuple[str | None, ...]:
        return tuple(read.card for read in self.hero_reads)

    @property
    def board_cards(self) -> tuple[str | None, ...]:
        return tuple(read.card for read in self.board_reads if not read.is_empty)

    @property
    def actionable(self) -> bool:
        return self.hero_turn and self.state.street is not None and bool(self.state.available_actions)

    def _comparison_key(self) -> tuple[object, ...]:
        """Keep the original stability/pre-click comparison, including unknown slots."""
        state = self.state
        return (
            self.hero_turn, self.hero_cards, self.board_cards, state.street,
            state.available_actions, state.to_call, state.raise_amount, state.pot_bb,
            state.hero_stack_bb, state.effective_stack_bb, state.active_players,
            state.hero_position, state.action_history,
        )

    def __eq__(self, other: object) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return self._comparison_key() == other._comparison_key()

    def __hash__(self) -> int:
        return hash(self._comparison_key())


@dataclass
class StableObservationDetector:
    """Accept a decision snapshot only after identical consecutive reads."""

    required_frames: int = STABLE_DECISION_FRAMES
    candidate: TableObservation | None = None
    candidate_frames: int = 0

    def __post_init__(self) -> None:
        if self.required_frames < 2:
            raise ValueError("required_frames must be at least two")

    def reset(self) -> None:
        self.candidate = None
        self.candidate_frames = 0

    def observe(self, observation: TableObservation) -> TableObservation | None:
        if not observation.actionable:
            self.reset()
            return None
        if observation == self.candidate:
            self.candidate_frames += 1
        else:
            self.candidate = observation
            self.candidate_frames = 1
        return observation if self.candidate_frames >= self.required_frames else None


@dataclass
class HeroTurnScreenshotCache:
    """Reuse one screenshot while the same hero turn remains visible."""

    key: tuple[object, ...] | None = None
    screenshot: bytes | None = None
    vision_state: object | None = None

    def reset(self) -> None:
        self.key = None
        self.screenshot = None
        self.vision_state = None

    def read(self, page, vision_reader, key: tuple[object, ...]):
        if self.key != key or self.screenshot is None or self.vision_state is None:
            self.screenshot = page.screenshot()
            self.vision_state = vision_reader.read_screenshot(self.screenshot)
            self.key = key
        return self.screenshot, self.vision_state


def preflop_position_from_action_history(action_history: tuple[str, ...]) -> str | None:
    """Infer first-action position in an unraised pot from prior seat actions."""
    if any(action.startswith("RAISE") for action in action_history):
        return None
    if len(action_history) >= len(PREFLOP_ACTION_ORDER):
        return None
    return PREFLOP_ACTION_ORDER[len(action_history)]


def six_max_position(
    hero: tuple[float, float] | None,
    button: tuple[float, float] | None,
    table_center: tuple[float, float] | None,
    table_bounds: tuple[float, float, float, float] | None = None,
) -> str | None:
    """Map hero's seat to BTN/SB/BB/UTG/HJ/CO from dealer geometry."""
    if hero is None or button is None or table_center is None:
        return None

    if table_bounds is not None:
        table_x, table_y, table_width, table_height = table_bounds
        if table_width <= 0 or table_height <= 0:
            return None
        anchors = (
            (0.50, 0.15),
            (0.91, 0.30),
            (0.91, 0.65),
            (0.50, 0.86),
            (0.09, 0.65),
            (0.09, 0.30),
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
    steps = ((hero_angle - button_angle) % (2 * pi)) / (2 * pi / len(SIX_MAX_POSITIONS))
    if abs(steps - round(steps)) > 1 / 3:
        return None
    return SIX_MAX_POSITIONS[round(steps) % len(SIX_MAX_POSITIONS)]


def _read_six_max_position(page: "Page") -> str | None:
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
              const a = first.getBoundingClientRect(), b = second.getBoundingClientRect();
              return a.width * a.height - b.width * b.height;
            })[0];
          const tableRect = table?.getBoundingClientRect();
          return {table: center(table), button: center(button), hero: center(action),
            tableBounds: tableRect ? [tableRect.x, tableRect.y, tableRect.width, tableRect.height] : null};
        }"""
    )
    return six_max_position(
        tuple(geometry["hero"]) if geometry["hero"] is not None else None,
        tuple(geometry["button"]) if geometry["button"] is not None else None,
        tuple(geometry["table"]) if geometry["table"] is not None else None,
        tuple(geometry["tableBounds"]) if geometry["tableBounds"] is not None else None,
    )


def board_needs_screenshot_fallback(sources: tuple[str | None, ...]) -> bool:
    """Return whether a missing DOM source occurs within the dealt board."""
    dealt_indices = [index for index, source in enumerate(sources) if source is not None]
    if not dealt_indices:
        return True
    return any(source is None for source in sources[: dealt_indices[-1] + 1])


def _needs_screenshot(
    hero_turn: bool,
    has_dom_hero: bool,
    board_sources: tuple[str | None, ...],
) -> bool:
    """Capture only when a hero decision cannot be read safely from the DOM."""
    return hero_turn and (
        not has_dom_hero or board_needs_screenshot_fallback(board_sources)
    )


def _read_dom_board(dom_card_matcher, sources, screenshot_state=None) -> tuple[CardRead, ...]:
    return tuple(
        dom_card_matcher.read(source)
        if source is not None
        else (
            screenshot_state.board[index]
            if screenshot_state is not None
            else CardRead(card=None, confidence=1.0, is_empty=True)
        )
        for index, source in enumerate(sources)
    )


def _is_hero_turn(page: "Page", layout) -> bool:
    return bool(
        page.locator("*").evaluate_all(
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
            [
                layout.action_badge.x,
                layout.action_badge.y,
                layout.action_badge.width,
                layout.action_badge.height,
            ],
        )
    )


def read_table_observation(
    page,
    vision_reader,
    dom_card_matcher,
    stage_detector=None,
    screenshot_cache: HeroTurnScreenshotCache | None = None,
) -> TableObservation:
    """Read cards, controls, betting facts, and position through one path."""
    raw_text = page.locator("body").inner_text(timeout=2_000)
    parsed = parse_visible_state(raw_text, read_coaching_hand=False)
    if vision_reader is None:
        actions = available_actions(page)
        return TableObservation(
            hero_turn=False,
            state=replace(
                parsed,
                available_actions=actions,
                can_check="CHECK" in actions,
                to_call=live_call_amount(page) if "CALL" in actions else None,
                raise_amount=live_raise_amount(page) if "RAISE" in actions else None,
            ),
            raw_text=raw_text,
            parsed_state=parsed, hero_reads=(), board_reads=(), hero_sources=(),
            board_sources=(), screenshot=None,
        )

    from src.vision.dom_cards import board_card_sources, hero_card_sources
    from src.vision.reader import VisionState
    from src.vision.stage import stage_from_board

    hero_sources = hero_card_sources(page, vision_reader.layout)
    board_sources = board_card_sources(page, vision_reader.layout)
    hero_turn = _is_hero_turn(page, vision_reader.layout)
    has_dom_hero = bool(hero_sources) and all(source is not None for source in hero_sources)
    screenshot = None
    screenshot_state = None
    if not hero_turn and screenshot_cache is not None:
        screenshot_cache.reset()
    if _needs_screenshot(hero_turn, has_dom_hero, board_sources):
        capture_key = (
            parsed.street,
            tuple(source is not None for source in hero_sources),
            tuple(source is not None for source in board_sources),
        )
        if screenshot_cache is None:
            screenshot = page.screenshot()
            screenshot_state = vision_reader.read_screenshot(screenshot)
        else:
            screenshot, screenshot_state = screenshot_cache.read(
                page,
                vision_reader,
                capture_key,
            )

    if has_dom_hero:
        vision_state = VisionState(
            hero=tuple(dom_card_matcher.read(source) for source in hero_sources),
            board=_read_dom_board(dom_card_matcher, board_sources, screenshot_state),
        )
    elif screenshot_state is not None:
        vision_state = screenshot_state
    else:
        # A non-actionable frame never needs an image capture. Empty hero cards
        # force the strategy to remain inactive until the next hero turn.
        vision_state = VisionState(
            hero=tuple(
                CardRead(card=None, confidence=1.0, is_empty=True)
                for _ in vision_reader.layout.hero
            ),
            board=_read_dom_board(dom_card_matcher, board_sources),
        )

    street = (
        stage_detector.observe(vision_state.board)
        if stage_detector is not None
        else stage_from_board(vision_state.board)
    )
    hero_position = _read_six_max_position(page) if hero_turn else None
    if hero_turn and street == "preflop" and hero_position is None:
        hero_position = preflop_position_from_action_history(parsed.action_history)
    actions = available_actions(page)
    call_amount = live_call_amount(page) if "CALL" in actions else None
    raise_amount = live_raise_amount(page) if "RAISE" in actions else None
    pot_amount = live_pot_amount(page, vision_reader.layout) or parsed.pot_bb
    state = replace(
        with_vision_hand(
            parsed,
            vision_state.hero_cards,
            tuple(read.card for read in vision_state.board if not read.is_empty),
        ),
        street=street,
        hero_position=hero_position,
        can_check="CHECK" in actions,
        to_call=call_amount,
        pot_bb=pot_amount,
        available_actions=actions,
        raise_amount=raise_amount,
    )
    return TableObservation(
        hero_turn=hero_turn,
        state=state,
        raw_text=raw_text,
        parsed_state=parsed,
        hero_reads=vision_state.hero,
        board_reads=vision_state.board,
        hero_sources=hero_sources,
        board_sources=board_sources,
        screenshot=screenshot,
    )


@dataclass
class GambitTableReader:
    """Single entry point for normal polling and pre-click table reads."""

    page: object
    vision_reader: object | None
    dom_card_matcher: object | None
    stage_detector: object | None = None
    screenshot_cache: HeroTurnScreenshotCache = field(
        default_factory=HeroTurnScreenshotCache
    )

    def read(self, stabilize_stage: bool = True) -> TableObservation:
        return read_table_observation(
            self.page,
            self.vision_reader,
            self.dom_card_matcher,
            self.stage_detector if stabilize_stage else None,
            self.screenshot_cache,
        )
