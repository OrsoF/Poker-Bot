"""Visible, user-authenticated Gambit table observer and action runner."""

from dataclasses import asdict, replace
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
from src.strategy.allin import ALL_IN_HANDS, decide as decide_allin
from src.strategy.conservative import Recommendation, decide

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
    display_action: str | None = None,
) -> bool:
    """Validate and click the exact action chosen by the pure strategy."""
    action = decision.action
    label = display_action or action.title()
    if action == "ALL_IN":
        return _apply_all_in(page, decision, expected_observation, observation_reader)
    if action not in expected_observation.state.available_actions:
        print(f"ANNULÉ: {label} — action indisponible")
        return False
    expected_amount = {
        "CALL": expected_observation.state.to_call,
        "RAISE": expected_observation.state.raise_amount,
    }.get(action)
    if decision.amount != expected_amount:
        print(f"ANNULÉ: {label} — montant différent de la table")
        return False
    sleep(uniform(0, 1))
    current_observation = observation_reader()
    if current_observation != expected_observation:
        print(f"ANNULÉ: {label} — état de la table modifié")
        return False
    control = _find_action_control(page, action)
    if control is None:
        print(f"ANNULÉ: {label} — bouton indisponible")
        return False
    control.click(timeout=2_000)
    print(f"OK: {label} effectué")
    return True


def _apply_all_in(
    page: "Page",
    decision: Recommendation,
    expected_observation: TableObservation,
    observation_reader: Callable[[], TableObservation],
) -> bool:
    """Select All-In sizing, then validate its numeric submission button."""
    if not expected_observation.actionable or decide_allin(expected_observation.state).action != "ALL_IN":
        print("ANNULÉ: All-In — cartes préflop ou boutons non confirmés")
        return False
    sleep(uniform(0, 1))
    if observation_reader() != expected_observation:
        print("ANNULÉ: All-In — état de la table modifié")
        return False
    control = _find_action_control(page, "ALL_IN")
    if control is None:
        print("ANNULÉ: All-In — bouton de mise indisponible")
        return False
    control.click(timeout=2_000)
    prepared = observation_reader()
    amount = prepared.state.raise_amount
    if (
        decide_allin(prepared.state).action != "ALL_IN"
        or prepared != replace(
            expected_observation,
            state=replace(
                expected_observation.state,
                raise_amount=amount,
                all_in_amount=prepared.state.all_in_amount,
            ),
        )
        or amount < expected_observation.state.raise_amount
        or (
            amount == expected_observation.state.raise_amount
            and amount != prepared.state.hero_stack_bb
            and amount != prepared.state.all_in_amount
        )
    ):
        print("ANNULÉ: All-In — mise non confirmée ou état modifié")
        return False
    return _apply_action(
        page, Recommendation("RAISE", decision.reason, amount=amount),
        prepared, observation_reader, display_action="All-In",
    )


def _print_vision_state(
    observation: TableObservation,
    show_hand_strength: bool,
) -> None:
    print(f"CARTES: {_format_card_reads(observation.hero_reads)}")
    if observation.state.street != "preflop":
        print(f"BOARD: {_format_card_reads(observation.board_reads)}")
    if show_hand_strength:
        from src.vision.hand_strength import evaluate_hand

        strength = evaluate_hand(observation.hero_cards, observation.board_cards)
        if strength is not None:
            print(f"HAND: {observation.state.street or '?'} | {strength.text}")
        elif observation.state.street != "preflop":
            print("HAND: indisponible (cartes non confirmées)")


def _format_card_reads(cards) -> str:
    """Show accepted cards and the best candidate for low-confidence matches."""
    parts = []
    for card in cards:
        if card.is_empty:
            continue
        label = card.card or f"{card.candidate or '?'}?"
        parts.append(label if card.card else f"{label} ({card.confidence:.0%})")
    return " ".join(parts) or "non confirmées"


def _decision_reason(decision: Recommendation, observation: TableObservation, strategy: str) -> str:
    """Shorten console explanations; preserve the policy reason in the audit."""
    state = observation.state
    reason = decision.reason
    if strategy == "allin":
        if decision.action == "ALL_IN":
            return f"{state.hand} dans le range allin"
        if reason.startswith("All-in sizing or raise amount is unavailable"):
            return "Montant du tapis non confirmé"
        if reason.startswith("All-in requires confirmed preflop cards"):
            if state.street != "preflop":
                return "Tapis réservé au préflop"
            if state.hand is None or None in state.hero_cards or len(state.hero_cards) != 2:
                return "Cartes non confirmées"
            if state.hand not in ALL_IN_HANDS:
                return f"{state.hand} hors range allin"
            return "Lecture incompatible avec un tapis"
    return reason.removesuffix("; fail-safe fold").removesuffix("; action is unavailable")


def _print_decision(
    observation: TableObservation,
    decision: Recommendation,
    hand_number: int,
    strategy: str,
    show_hand_strength: bool,
    previous_seats: tuple | None,
) -> tuple:
    state = observation.state
    street = {"preflop": "PRÉFLOP", "flop": "FLOP", "turn": "TURN", "river": "RIVER"}.get(state.street, "INCONNU")
    print(f"\nMAIN {hand_number} · {street}")
    _print_vision_state(observation, show_hand_strength)
    details = []
    missing = []
    for label, value in (("Position", state.hero_position), ("Tapis", state.hero_stack_bb),
                         ("Effectif", state.effective_stack_bb), ("Joueurs actifs", state.active_players)):
        if value is None:
            missing.append(label.lower())
        elif label in {"Tapis", "Effectif"}:
            details.append(f"{label} {value:g} BB")
        else:
            details.append(f"{label} {value}")
    if state.can_check:
        details.append("Check gratuit")
    elif state.to_call is not None:
        details.append(f"À payer {state.to_call:g} BB")
    else:
        missing.append("montant à payer")
    if details:
        print(" · ".join(details))
    if missing:
        print("LECTURE INCOMPLÈTE: " + ", ".join(missing))
    seats_key = tuple((seat.seat_index, seat.name, seat.position, seat.is_hero, seat.is_dealer)
                      for seat in state.seats)
    if seats_key and seats_key != previous_seats:
        print("SIÈGES: " + " | ".join(
            f"{'Hero' if seat.is_hero else seat.name or '?'} {seat.position or '?'} "
            + (f"{seat.stack_bb:g} BB" if seat.stack_bb is not None else "tapis inconnu")
            for seat in state.seats
        ))
    amount = f" {decision.amount:g} BB" if decision.amount is not None else ""
    print(f"DÉCISION: {decision.action}{amount} — {_decision_reason(decision, observation, strategy)}")
    return seats_key


def _state_summary(state) -> str:
    """Produce a stable terminal summary without dumping all visible page text."""
    call = "?" if state.to_call is None else f"{state.to_call:g} BB"
    hero_stack = next((seat.stack_bb for seat in state.seats if seat.is_hero), state.hero_stack_bb)
    stack = "?" if hero_stack is None else f"{hero_stack:g} BB"
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
    previous: tuple[str, str, str] | None,
    recorder: ObservationRecorder | None,
    record_dom: bool,
    quiet: bool = False,
) -> tuple[str, str, str]:
    seats = observation.state.seats
    hero_turn = "yes" if observation.hero_turn else "no"
    summary = f"STATE: {_state_summary(observation.state)} hero_turn={hero_turn}"
    seats_summary = "SEATS: " + " | ".join(
        f"{'Hero' if seat.is_hero else seat.name or '?'} {seat.position or '?'} "
        + (f"{seat.stack_bb:g} BB" if seat.stack_bb is not None else "? BB")
        for seat in seats
    ) if seats else "SEATS: unavailable"
    audit_key = observation.raw_text + repr(observation.state) + hero_turn
    previous_audit, previous_state, previous_seats = previous or ("", "", "")
    if not quiet and summary != previous_state:
        print(summary)
    if not quiet and seats_summary != previous_seats:
        print(seats_summary)
    if recorder is not None and audit_key != previous_audit:
        recorder.write(
            observation.raw_text,
            replace(observation.parsed_state, hero_position=observation.state.hero_position, seats=seats),
            hero_turn=observation.hero_turn,
            dom_map=visible_dom_map(page) if record_dom else None,
            observed_state=observation.state,
        )
    return audit_key, summary, seats_summary


def observe_table(
    interval_seconds: float,
    target_url: str | None = None,
    record: bool = False,
    auto_play: bool = False,
    record_dom: bool = False,
    vision: bool = False,
    hand_strength: bool = False,
    strategy: str = "conservative",
) -> None:
    """Open a headed browser and summarize stable decisions until Ctrl+C."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    validate_gambit_url(target_url)
    if strategy not in {"conservative", "allin"}:
        raise ValueError("strategy must be conservative or allin")
    decision_policy = decide_allin if strategy == "allin" else decide

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
        play_bots_pending = auto_play and target_url is None
        if play_bots_pending:
            print("Browser open. Sign in manually if needed; Play Bots will open automatically.")
        else:
            print("Browser open. Sign in manually, navigate to your table, then watch this terminal.")
        recorder = ObservationRecorder() if record else None
        if recorder is not None:
            print(f"Recording visible state changes to: {recorder.path}")
        known_card_count = dom_card_matcher.card_count if dom_card_matcher is not None else None
        if known_card_count is not None:
            print(f"CARTES CONNUES: {known_card_count}/52")

        previous = None
        previous_decision_seats = None
        hand_number = 1
        decision_reported_observation: TableObservation | None = None
        between_hands = False
        rebuy_clicked = False
        try:
            while True:
                try:
                    if auto_play:
                        rebuy_control = _visible_text_control(page, "Rebuy")
                        if rebuy_control is not None:
                            if not rebuy_clicked:
                                rebuy_control.click(timeout=2_000)
                                rebuy_clicked = True
                                print("OK: Rebuy effectué")
                                observation_detector.reset()
                                table_reader.screenshot_cache.reset()
                                if stage_detector is not None:
                                    stage_detector.reset()
                                hand_number += 1
                                decision_reported_observation = None
                                prompted_unknown_cards.clear()
                                between_hands = False
                            sleep(interval_seconds)
                            continue
                        rebuy_clicked = False
                    if play_bots_pending:
                        play_bots_control = _visible_text_control(page, "Play Bots")
                        if play_bots_control is not None:
                            play_bots_control.click(timeout=2_000)
                            play_bots_pending = False
                            print("OK: Play Bots ouvert")
                            sleep(interval_seconds)
                            continue
                    observation = table_reader.read()
                    if vision and observation.hero_turn:
                        observation = train_unknown_cards(
                            observation,
                            table_reader,
                            vision_reader,
                            dom_card_matcher,
                            prompted_unknown_cards,
                        )
                        if dom_card_matcher.card_count != known_card_count:
                            known_card_count = dom_card_matcher.card_count
                            print(f"CARTES CONNUES: {known_card_count}/52")
                    previous = _print_state(
                        page,
                        observation,
                        previous,
                        recorder,
                        record_dom,
                        quiet=vision,
                    )
                    next_hand_visible = _visible_text_control(page, "Next Hand") is not None
                    if next_hand_visible and not between_hands:
                        if vision_reader is not None:
                            stage_detector.reset()
                        decision_reported_observation = None
                        observation_detector.reset()
                        if vision_reader is not None:
                            prompted_unknown_cards.clear()
                        between_hands = True
                    elif not next_hand_visible:
                        if between_hands:
                            hand_number += 1
                        between_hands = False
                    if auto_play and _next_hand_if_available(page):
                        print("OK: Main suivante")
                        decision_reported_observation = None
                        observation_detector.reset()
                        sleep(interval_seconds)
                        continue
                    stable_observation = observation_detector.observe(observation)
                    if (
                        vision
                        and stable_observation is not None
                        and stable_observation != decision_reported_observation
                    ):
                        decision_state = stable_observation.state
                        decision = decision_policy(decision_state)
                        previous_decision_seats = _print_decision(
                            stable_observation, decision, hand_number, strategy,
                            hand_strength, previous_decision_seats,
                        )
                        decision_reported_observation = stable_observation
                        if recorder is not None:
                            recorder.write(
                                stable_observation.raw_text,
                                stable_observation.parsed_state,
                                hero_turn=stable_observation.hero_turn,
                                observed_state=decision_state,
                                decision=asdict(decision),
                                hand_number=hand_number,
                            )
                        if auto_play and decision.action in {"FOLD", "CHECK", "CALL", "RAISE", "ALL_IN"}:
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
