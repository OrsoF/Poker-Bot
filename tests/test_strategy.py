from dataclasses import replace

from src.models import ObservedState
from src.reader.game_state import parse_visible_state, with_vision_hand
from src.strategy.allin import decide as decide_allin
from src.strategy.conservative import decide, recommend


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


def test_allin_pushes_only_confirmed_preflop_range() -> None:
    base = ObservedState(
        hand=None, street="preflop", to_call=10, big_blind=1, can_check=False,
        hero_position=None, hero_stack_bb=None, action_history=("RAISE 10 BB",),
        available_actions=frozenset({"ALL_IN", "RAISE", "CALL", "FOLD"}), raise_amount=20,
    )
    allowed_hands = (
        ("7s", "7h"), ("8s", "8h"), ("9s", "9h"), ("Ts", "Th"),
        ("As", "Ah"), ("Ks", "Kh"), ("Qs", "Qh"), ("Js", "Jh"),
        ("As", "9s"), ("As", "Ts"), ("As", "Js"), ("As", "Qs"), ("As", "Ks"),
        ("Ks", "Js"), ("Ks", "Qs"), ("Qs", "Js"),
        ("As", "Jh"), ("As", "Qh"), ("As", "Kh"), ("Ks", "Qh"),
    )
    for cards in allowed_hands:
        state = with_vision_hand(base, cards)
        assert decide_allin(state).action == "ALL_IN"
        assert decide(state).action == "FOLD"
        for position in (None, "UTG", "HJ", "CO", "BTN", "SB", "BB"):
            for stack in (None, 0.5, 1000):
                free_check = replace(
                    state, hero_position=position, hero_stack_bb=stack,
                    can_check=True, available_actions=state.available_actions | {"CHECK"},
                )
                assert decide_allin(free_check).action == "ALL_IN"

        # Enlarging allin must not enlarge the default opening policy.
        opening = replace(state, hero_position="HJ", to_call=1, action_history=())
        expected_default = (
            "RAISE" if state.hand in {"AA", "KK", "QQ", "JJ", "AKs", "AQs", "AKo"} else "FOLD"
        )
        assert decide(opening).action == expected_default

    state = with_vision_hand(base, ("As", "Kh"))
    blocked = [
        with_vision_hand(base, ("6s", "6h")),
        with_vision_hand(base, ("As", "8s")),
        with_vision_hand(base, ("Ks", "Ts")),
        with_vision_hand(base, ("Qs", "Ts")),
        with_vision_hand(base, ("As", "Th")),
        with_vision_hand(base, ("Ks", "Jh")),
        with_vision_hand(base, ("Qs", "Jh")),
        with_vision_hand(base, ("As", None)),
        replace(state, hero_cards=()),
        replace(state, hero_cards=("As", "As")),
        replace(state, hero_cards=("As", None)),
        replace(state, board_cards=("2s", "3h", "4d")),
    ]
    blocked += [replace(state, street=street) for street in (None, "flop", "turn", "river")]
    for unsafe in blocked:
        assert decide_allin(unsafe).action == "FOLD"
        assert decide_allin(replace(unsafe, available_actions=unsafe.available_actions | {"CHECK"})).action == "CHECK"
    assert decide_allin(replace(state, available_actions=frozenset())).action == "NO_ACTION"

    missing_sizing = [
        replace(state, available_actions=frozenset({"RAISE", "FOLD"})),
        replace(state, available_actions=frozenset({"ALL_IN", "FOLD"})),
    ] + [replace(state, raise_amount=amount) for amount in (None, 0, -1, float("nan"), float("inf"))]
    for unsafe in missing_sizing:
        assert decide_allin(unsafe).action == "NO_ACTION"
        assert decide_allin(replace(unsafe, available_actions=unsafe.available_actions | {"CHECK"})).action == "CHECK"
