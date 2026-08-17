"""Visible, user-authenticated Gambit table observer and action runner."""

from dataclasses import replace
from random import uniform
from time import sleep
from typing import TYPE_CHECKING, Callable

from src.browser.gambit_config import GAMBIT_URL, PROFILE_DIRECTORY, validate_gambit_url
from src.browser.gambit_controls import (
    click_next_hand,
    find_action_control,
    visible_text_control,
)
from src.browser.gambit_inspector import inspect_table, visible_dom_map
from src.browser.gambit_observation import (
    GambitTableReader,
    StableObservationDetector,
    TableObservation,
)
from src.browser.gambit_training import train_unknown_cards
from src.reader.recorder import ObservationRecorder
from src.strategy.conservative import Recommendation, decide, with_vision_hand

if TYPE_CHECKING:
    from playwright.sync_api import Page


_visible_text_control = visible_text_control
_find_action_control = find_action_control
_next_hand_if_available = click_next_hand


def _apply_action(
    page: "Page",
    decision: Recommendation,
    expected_observation: TableObservation,
    observation_reader: Callable[[], TableObservation],
) -> bool:
    """Validate and click the exact action chosen by the pure strategy."""
    action = decision.action
    if action not in expected_observation.available_actions:
        print(f"ACTION: {action.title()} unavailable — not present in the stable observation")
        return False
    expected_amount = {
        "CALL": expected_observation.call_amount,
        "RAISE": expected_observation.raise_amount,
    }.get(action)
    if decision.amount != expected_amount:
        print(f"ACTION: {action.title()} cancelled — strategy amount does not match the table")
        return False
    sleep(uniform(0, 1))
    current_observation = observation_reader()
    if current_observation != expected_observation:
        print(f"ACTION: {action.title()} cancelled — table observation changed")
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
    observation: TableObservation,
    show_hand_strength: bool,
) -> None:
    print(
        "TURN: "
        f"stage={observation.street or '?'} "
        f"hero=[{_format_card_reads(observation.hero_reads)}] "
        f"board=[{_format_card_reads(observation.board_reads)}] "
        f"known={dom_card_matcher.card_count}/52"
    )
    if show_hand_strength:
        from src.strategy.hand_strength import evaluate_hand

        strength = evaluate_hand(observation.hero_cards, observation.board_cards)
        if strength is not None:
            print(f"HAND: {observation.street or '?'} | {strength.text}")
        elif observation.street == "preflop":
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


def _print_state(
    page: "Page",
    observation: TableObservation,
    previous: str,
    recorder: ObservationRecorder | None,
    record_dom: bool,
) -> str:
    summary = " ".join(observation.raw_text.split())[:500]
    if summary != previous:
        state = replace(observation.parsed_state, hero_position=observation.hero_position)
        hero_turn = "yes" if observation.hero_turn else "no"
        print(f"STATE: {_state_summary(state)} hero_turn={hero_turn}")
        if recorder is not None:
            recorder.write(
                observation.raw_text,
                state,
                hero_turn=observation.hero_turn,
                dom_map=visible_dom_map(page) if record_dom else None,
            )
    return summary


def _strategy_state(observation: TableObservation):
    """Translate one canonical table observation into pure strategy input."""
    state = with_vision_hand(
        observation.parsed_state,
        observation.hero_cards,
        observation.board_cards,
    )
    return replace(
        state,
        street=observation.street,
        hero_position=observation.hero_position,
        can_check="CHECK" in observation.available_actions,
        to_call=observation.call_amount,
        pot_bb=observation.pot_amount,
        hero_stack_bb=observation.hero_stack,
        effective_stack_bb=observation.effective_stack,
        active_players=observation.active_players,
        action_history=observation.action_history,
        available_actions=observation.available_actions,
        raise_amount=observation.raise_amount,
    )


def observe_table(
    interval_seconds: float,
    target_url: str | None = None,
    record: bool = False,
    auto_play: bool = False,
    record_dom: bool = False,
    vision: bool = False,
    hand_strength: bool = False,
) -> None:
    """Open a headed browser and print state changes until Ctrl+C is pressed."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    validate_gambit_url(target_url)

    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install -r requirements.txt"
        ) from error

    vision_reader = None
    dom_card_matcher = None
    stage_detector = None
    observation_detector = StableObservationDetector()
    prompted_unknown_cards: set[str] = set()
    if vision or auto_play:
        from src.vision.layout import load_layout
        from src.vision.reader import VisionReader

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

    PROFILE_DIRECTORY.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIRECTORY.resolve()),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url or GAMBIT_URL, wait_until="domcontentloaded")
        table_reader = GambitTableReader(
            page,
            vision_reader,
            dom_card_matcher,
            stage_detector,
        )
        print("Browser open. Sign in manually, navigate to your table, then watch this terminal.")
        recorder = ObservationRecorder() if record else None
        if recorder is not None:
            print(f"Recording visible state changes to: {recorder.path}")

        previous = ""
        vision_turn_active = False
        vision_reported_stage: str | None = None
        decision_reported_observation: TableObservation | None = None
        between_hands = False
        try:
            while True:
                try:
                    observation = table_reader.read()
                    if vision and observation.hero_turn:
                        observation = train_unknown_cards(
                            observation,
                            table_reader,
                            vision_reader,
                            dom_card_matcher,
                            prompted_unknown_cards,
                        )
                    previous = _print_state(
                        page,
                        observation,
                        previous,
                        recorder,
                        record_dom,
                    )
                    next_hand_visible = _visible_text_control(page, "Next Hand") is not None
                    if next_hand_visible and not between_hands:
                        if vision_reader is not None:
                            stage_detector.reset()
                        vision_turn_active = False
                        vision_reported_stage = None
                        decision_reported_observation = None
                        observation_detector.reset()
                        if vision_reader is not None:
                            prompted_unknown_cards.clear()
                        between_hands = True
                    elif not next_hand_visible:
                        between_hands = False
                    if auto_play and _next_hand_if_available(page):
                        print("ACTION: Next Hand clicked")
                        vision_turn_active = False
                        vision_reported_stage = None
                        decision_reported_observation = None
                        observation_detector.reset()
                        sleep(interval_seconds)
                        continue
                    stable_observation = observation_detector.observe(observation)
                    if (
                        vision
                        and observation.hero_turn
                        and (
                            not vision_turn_active
                            or observation.street != vision_reported_stage
                        )
                    ):
                        _print_vision_state(
                            dom_card_matcher,
                            observation,
                            hand_strength,
                        )
                        vision_turn_active = True
                        vision_reported_stage = observation.street
                    if not observation.hero_turn:
                        vision_turn_active = False
                        vision_reported_stage = None
                    if (
                        vision
                        and stable_observation is not None
                        and stable_observation != decision_reported_observation
                    ):
                        decision_state = _strategy_state(stable_observation)
                        decision = decide(decision_state)
                        position = decision_state.hero_position or "?"
                        stack = (
                            "?"
                            if decision_state.hero_stack_bb is None
                            else f"{decision_state.hero_stack_bb:g} BB"
                        )
                        print(
                            f"DECISION: {decision.action} — {decision.reason} "
                            f"[position={position} stack={stack}]"
                        )
                        decision_reported_observation = stable_observation
                        if auto_play and decision.action in {"FOLD", "CHECK", "CALL", "RAISE"}:
                            action_applied = _apply_action(
                                page,
                                decision,
                                stable_observation,
                                lambda: table_reader.read(stabilize_stage=False),
                            )
                            observation_detector.reset()
                            if not action_applied:
                                # A cancelled action must earn two fresh stable
                                # frames before it may be attempted again.
                                decision_reported_observation = None
                    if not observation.hero_turn:
                        decision_reported_observation = None
                except Error as error:
                    # Tables can briefly re-render between polls; keep observing.
                    print(f"WAIT: {error.__class__.__name__}")
                sleep(interval_seconds)
        except KeyboardInterrupt:
            print("Observer stopped.")
        finally:
            context.close()
