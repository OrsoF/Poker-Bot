from dataclasses import replace

from src.reader.game_state import parse_visible_state
from src.strategy.conservative import ObservedState, decide, recommend, with_vision_hand


def test_safe_strategy_only_opens_confirmed_premiums() -> None:
    opening = ObservedState(
        hand="AKo",
        street="preflop",
        to_call=1,
        big_blind=1,
        can_check=False,
        hero_position="HJ",
        available_actions=frozenset({"FOLD", "CALL", "RAISE"}),
        raise_amount=2.5,
    )
    assert decide(opening).action == "RAISE"
    assert decide(opening).amount == 2.5

    unknown_position = replace(opening, hero_position=None)
    assert recommend(unknown_position).action == "FOLD"
    assert decide(unknown_position).action == "FOLD"

    facing_raise = with_vision_hand(
        ObservedState(
            hand="AKs",
            street="preflop",
            to_call=2,
            big_blind=1,
            can_check=False,
            hero_position="BTN",
            available_actions=frozenset({"FOLD", "CHECK", "CALL", "RAISE"}),
        ),
        ("Ah", "Kh"),
    )
    assert recommend(facing_raise).action == "FOLD"
    assert decide(replace(facing_raise, can_check=True)).action == "CHECK"

    parsed = parse_visible_state(
        "ACTION 91.0 BB Nora 110 BB RAISE 3.5 BB Wendy 173 BB FOLD "
        "Charles 19 BB FOLD Sakura 103 BB FOLD Maria 280 BB "
        "Call: 3.5 BB Raise: 10.5 BB"
    )
    assert (parsed.hero_stack_bb, parsed.effective_stack_bb, parsed.active_players) == (
        91.0,
        91.0,
        3,
    )
