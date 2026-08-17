from dataclasses import replace

from src.reader.game_state import has_live_action_panel, parse_visible_state
from src.strategy.conservative import ObservedState, recommend, with_vision_hand
from src.vision.cards import CardRead
from src.browser.gambit import _format_card_reads


def test_parses_and_folds_non_premium_preflop_hand() -> None:
    state = parse_visible_state("10-4 offsuit is a tough hand. Call: 2")
    assert state.hand == "T4o"
    assert state.street == "preflop"
    assert recommend(state).action == "FOLD"


def test_recommends_opening_ak_suited_from_the_button() -> None:
    state = ObservedState(hand="AKs", street="preflop", to_call=1, big_blind=1, can_check=False, hero_position="BTN")
    assert recommend(state).action == "RAISE"


def test_calls_additional_hands_in_the_conservative_preflop_range() -> None:
    cards_by_hand = {
        "77": ("7s", "7h"),
        "ATs": ("As", "Ts"),
        "KQo": ("Kh", "Qd"),
        "JTs": ("Jh", "Th"),
    }
    for hand, cards in cards_by_hand.items():
        state = ObservedState(
            hand=hand,
            street="preflop",
            to_call=2,
            big_blind=1,
            can_check=False,
            hero_position="BTN",
            pot_bb=4,
            effective_stack_bb=100,
            active_players=2,
        )
        assert recommend(with_vision_hand(state, cards), equity_samples=300).action == "CALL"


def test_folds_hands_outside_the_conservative_preflop_range() -> None:
    state = ObservedState(hand="A9o", street="preflop", to_call=2, big_blind=1, can_check=False)
    assert recommend(state).action == "FOLD"


def test_unknown_position_does_not_invent_an_opening_range() -> None:
    state = ObservedState(hand="AKs", street="preflop", to_call=1, big_blind=1, can_check=False)
    assert recommend(state).action == "NO_ACTION"


def test_folds_a_hand_outside_the_conservative_three_bet_continue_range() -> None:
    state = ObservedState(
        hand="AQo", street="preflop", to_call=9, big_blind=1, can_check=False,
        action_history=("RAISE 3 BB", "RAISE 9 BB"),
    )
    assert recommend(state).action == "FOLD"


def test_unknown_street_does_not_guess_an_action() -> None:
    assert recommend(parse_visible_state("Call: 2")).action == "NO_ACTION"


def test_parses_gambit_postflop_pot_fraction_controls() -> None:
    state = parse_visible_state("1/3 1/2 3/4 Pot All-In Check Bet: 11")
    assert state.street == "postflop"
    assert state.can_check
    assert recommend(state).action == "CHECK"


def test_postflop_does_not_call_without_price_and_card_context() -> None:
    state = parse_visible_state("1/3 1/2 3/4 Pot All-In Fold Call: 2", big_blind=1)
    assert recommend(state).action == "FOLD"


def test_postflop_recommendation_uses_equity_and_price() -> None:
    state = ObservedState(
        hand="AKs",
        street="flop",
        to_call=2,
        big_blind=1,
        can_check=False,
        pot_bb=10,
        effective_stack_bb=100,
        active_players=2,
    )
    confirmed = with_vision_hand(state, ("Ah", "Kh"), ("Qh", "Jh", "2c"))
    assert recommend(confirmed, equity_samples=300).action == "CALL"
    assert recommend(replace(confirmed, to_call=30), equity_samples=300).action == "FOLD"


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


def test_parses_hero_stack_from_the_action_seat() -> None:
    state = parse_visible_state("91.0 BB ACTION Maria 280 BB Call: 3")
    assert state.hero_stack_bb == 91.0


def test_parses_visible_preflop_betting_context() -> None:
    state = parse_visible_state(
        "ACTION 91.0 BB Nora 110 BB RAISE 3.5 BB Wendy 173 BB FOLD "
        "Charles 19 BB FOLD Sakura 103 BB FOLD Maria 280 BB Call: 3.5 BB Raise: 10.5 BB"
    )
    assert state.current_raise_to_bb == 3.5
    assert state.minimum_raise_to_bb == 10.5
    assert state.active_players == 3
    assert state.effective_stack_bb == 91.0
    assert state.action_history == ("RAISE 3.5 BB", "FOLD", "FOLD", "FOLD")
