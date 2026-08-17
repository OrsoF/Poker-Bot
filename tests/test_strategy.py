from dataclasses import replace

from src.reader.game_state import parse_visible_state
from src.strategy.conservative import ObservedState, decide, recommend, with_vision_hand
from src.strategy.equity import assess_call, hole_cards_improve_board


def test_strategy_respects_position_legality_and_price() -> None:
    opening = ObservedState(
        hand="KQo",
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
    assert recommend(unknown_position).action == "NO_ACTION"
    assert decide(unknown_position).action == "FOLD"

    draw = with_vision_hand(
        ObservedState(
            hand="AKs",
            street="flop",
            to_call=2,
            big_blind=1,
            can_check=False,
            pot_bb=10,
            effective_stack_bb=100,
            active_players=2,
        ),
        ("Ah", "Kh"),
        ("Qh", "Jh", "2c"),
    )
    assert recommend(draw, equity_samples=400).action == "CALL"
    assert recommend(replace(draw, to_call=30), equity_samples=400).action == "FOLD"

    board = ("As", "Ac", "Kc")
    assert not hole_cards_improve_board(("9h", "8d"), board)
    assert not assess_call(
        hero=("9h", "8d"),
        board=board,
        to_call=1,
        pot=20,
        effective_stack=100,
        active_players=2,
        samples=300,
    ).should_call

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
