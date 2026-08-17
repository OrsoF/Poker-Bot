"""Canonical, immutable reads of a live Gambit table."""

from dataclasses import dataclass, field
from math import atan2, pi
from typing import TYPE_CHECKING

from src.browser.gambit_controls import (
    available_actions,
    live_call_amount,
    live_pot_amount,
    live_raise_amount,
)
from src.reader.game_state import parse_visible_state
from src.strategy.conservative import ObservedState
from src.vision.cards import CardRead

if TYPE_CHECKING:
    from playwright.sync_api import Page


SIX_MAX_POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
PREFLOP_ACTION_ORDER = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
STABLE_DECISION_FRAMES = 2


@dataclass(frozen=True)
class TableObservation:
    """One immutable read of every fact used to make a decision."""

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
    raw_text: str = field(compare=False, repr=False)
    parsed_state: ObservedState = field(compare=False, repr=False)
    hero_reads: tuple[CardRead, ...] = field(compare=False, repr=False)
    board_reads: tuple[CardRead, ...] = field(compare=False, repr=False)
    hero_sources: tuple[str | None, ...] = field(compare=False, repr=False)
    board_sources: tuple[str | None, ...] = field(compare=False, repr=False)
    screenshot: bytes | None = field(compare=False, repr=False)

    @property
    def actionable(self) -> bool:
        return self.hero_turn and self.street is not None and bool(self.available_actions)


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
) -> TableObservation:
    """Read cards, controls, betting facts, and position through one path."""
    raw_text = page.locator("body").inner_text(timeout=2_000)
    parsed = parse_visible_state(raw_text, read_coaching_hand=False)
    if vision_reader is None:
        actions = available_actions(page)
        return TableObservation(
            hero_turn=False, hero_cards=(), board_cards=(), street=parsed.street,
            available_actions=actions,
            call_amount=live_call_amount(page) if "CALL" in actions else None,
            raise_amount=live_raise_amount(page) if "RAISE" in actions else None,
            pot_amount=parsed.pot_bb, hero_stack=parsed.hero_stack_bb,
            effective_stack=parsed.effective_stack_bb, active_players=parsed.active_players,
            hero_position=None, action_history=parsed.action_history, raw_text=raw_text,
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
    if has_dom_hero:
        screenshot_state = None
        if hero_turn and board_needs_screenshot_fallback(board_sources):
            screenshot = page.screenshot()
            screenshot_state = vision_reader.read_screenshot(screenshot)
        vision_state = VisionState(
            hero=tuple(dom_card_matcher.read(source) for source in hero_sources),
            board=_read_dom_board(dom_card_matcher, board_sources, screenshot_state),
        )
    else:
        screenshot = page.screenshot()
        vision_state = vision_reader.read_screenshot(screenshot)

    street = (
        stage_detector.observe(vision_state.board)
        if stage_detector is not None
        else stage_from_board(vision_state.board)
    )
    hero_position = _read_six_max_position(page) if hero_turn else None
    if hero_turn and street == "preflop" and hero_position is None:
        hero_position = preflop_position_from_action_history(parsed.action_history)
    actions = available_actions(page)
    return TableObservation(
        hero_turn=hero_turn,
        hero_cards=vision_state.hero_cards,
        board_cards=tuple(read.card for read in vision_state.board if not read.is_empty),
        street=street,
        available_actions=actions,
        call_amount=live_call_amount(page) if "CALL" in actions else None,
        raise_amount=live_raise_amount(page) if "RAISE" in actions else None,
        pot_amount=live_pot_amount(page, vision_reader.layout) or parsed.pot_bb,
        hero_stack=parsed.hero_stack_bb,
        effective_stack=parsed.effective_stack_bb,
        active_players=parsed.active_players,
        hero_position=hero_position,
        action_history=parsed.action_history,
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

    def read(self, stabilize_stage: bool = True) -> TableObservation:
        return read_table_observation(
            self.page,
            self.vision_reader,
            self.dom_card_matcher,
            self.stage_detector if stabilize_stage else None,
        )
