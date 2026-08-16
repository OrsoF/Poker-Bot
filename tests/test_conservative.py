from src.reader.game_state import has_live_action_panel, parse_visible_state
from src.strategy.conservative import ObservedState, recommend, with_vision_hand
from src.vision.cards import CardRead
from src.browser.gambit import _format_card_reads


def test_parses_and_folds_non_premium_preflop_hand() -> None:
    state = parse_visible_state("10-4 offsuit is a tough hand. Call: 2")
    assert state.hand == "T4o"
    assert state.street == "preflop"
    assert recommend(state).action == "FOLD"


def test_calls_premium_preflop_hand() -> None:
    state = parse_visible_state("Ace-King suited")
    assert state.hand == "AKs"
    assert recommend(state).action == "CALL"


def test_unknown_street_does_not_guess_an_action() -> None:
    assert recommend(parse_visible_state("Call: 2")).action == "NO_ACTION"


def test_parses_gambit_postflop_pot_fraction_controls() -> None:
    state = parse_visible_state("1/3 1/2 3/4 Pot All-In Check Bet: 11")
    assert state.street == "postflop"
    assert state.can_check
    assert recommend(state).action == "CHECK"


def test_postflop_calls_are_limited_to_two_big_blinds() -> None:
    state = parse_visible_state("1/3 1/2 3/4 Pot All-In Fold Call: 2", big_blind=1)
    assert recommend(state).action == "CALL"


def test_fractional_call_amount_is_parsed() -> None:
    state = parse_visible_state("2x 2.5x 3x 4x All-In Fold Call: 0.5 BB")
    assert state.to_call == 0.5


def test_card_progress_shows_best_low_confidence_candidate() -> None:
    reads = (CardRead(card="8d", confidence=0.94, candidate="8d"), CardRead(card=None, confidence=0.65, candidate="Js"))
    assert _format_card_reads(reads) == "8d 94%, Js? 65%"


def test_live_action_panel_rejects_completed_hand() -> None:
    assert has_live_action_panel("All-In Fold Call: 2 Raise: 5")
    assert not has_live_action_panel("All-In Fold Next Hand")


def test_vision_hand_replaces_text_derived_hand() -> None:
    state = ObservedState(hand="K2o", street="preflop", to_call=1, big_blind=1, can_check=False)
    visual = with_vision_hand(state, ("As", "Kd"))
    assert visual.hand == "AKo"


def test_incomplete_vision_hand_defaults_to_preflop_fold() -> None:
    state = ObservedState(hand="K2o", street="preflop", to_call=1, big_blind=1, can_check=False)
    assert recommend(with_vision_hand(state, ("As", None))).action == "FOLD"


def test_preflop_panel_is_detected_without_coaching_text() -> None:
    state = parse_visible_state("2x 2.5x 3x 4x All-In Fold Call: 2", read_coaching_hand=False)
    assert state.street == "preflop"


def test_unknown_preflop_hand_checks_when_check_is_available() -> None:
    state = ObservedState(hand=None, street="preflop", to_call=0, big_blind=1, can_check=True)
    assert recommend(state).action == "CHECK"
