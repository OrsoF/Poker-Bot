"""A deliberately narrow first-pass poker policy.

It is designed for validation, not as a complete poker strategy. Ambiguous
state always yields NO_ACTION.
"""

from dataclasses import dataclass, replace

from src.strategy.equity import assess_call


PREFLOP_OPEN_RANGES = {
    "UTG": frozenset({"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "AKs", "AQs", "AJs", "ATs", "AKo", "AQo", "KQs"}),
    "HJ": frozenset({"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "AKs", "AQs", "AJs", "ATs", "AKo", "AQo", "AJo", "KQs", "KJs", "KQo", "QJs", "JTs"}),
    "CO": frozenset({"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "AKo", "AQo", "AJo", "KQs", "KJs", "KTs", "KQo", "QJs", "QTs", "JTs", "T9s", "98s"}),
    "BTN": frozenset({"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22", "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s", "AKo", "AQo", "AJo", "ATo", "A9o", "A8o", "KQs", "KJs", "KTs", "K9s", "K8s", "KQo", "KJo", "KTo", "QJs", "QTs", "Q9s", "QJo", "QTo", "JTs", "J9s", "JTo", "T9s", "98s", "87s", "76s"}),
    "SB": frozenset({"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22", "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s", "AKo", "AQo", "AJo", "ATo", "KQs", "KJs", "KTs", "K9s", "KQo", "KJo", "QJs", "QTs", "Q9s", "QJo", "JTs", "J9s", "T9s", "98s", "87s"}),
}
PREFLOP_CALL_OPEN = frozenset({"AA", "KK", "QQ", "JJ", "TT", "99", "AKs", "AQs", "AJs", "AKo", "AQo", "KQs"})
PREFLOP_CALL_OPEN_IN_POSITION = PREFLOP_CALL_OPEN | frozenset({"88", "77", "ATs", "KJs", "KQo", "QJs", "JTs"})
PREFLOP_3BET_CONTINUE = frozenset({"AA", "KK", "QQ", "JJ", "AKs", "AQs", "AKo"})


@dataclass(frozen=True)
class ObservedState:
    hand: str | None
    street: str | None
    to_call: float | None
    big_blind: float | None
    can_check: bool
    hero_stack_bb: float | None = None
    hero_position: str | None = None
    pot_bb: float | None = None
    current_raise_to_bb: float | None = None
    minimum_raise_to_bb: float | None = None
    active_players: int | None = None
    effective_stack_bb: float | None = None
    action_history: tuple[str, ...] = ()
    hero_cards: tuple[str, ...] = ()
    board_cards: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recommendation:
    action: str
    reason: str


def _priced_call(state: ObservedState, samples: int) -> Recommendation:
    assessment = assess_call(
        hero=state.hero_cards,
        board=state.board_cards,
        to_call=state.to_call,
        pot=state.pot_bb,
        effective_stack=state.effective_stack_bb,
        active_players=state.active_players,
        samples=samples,
    )
    return Recommendation("CALL" if assessment.should_call else "FOLD", assessment.reason)


def recommend(state: ObservedState, equity_samples: int = 1_200) -> Recommendation:
    """Return a conservative decision without touching the browser."""
    if state.street == "preflop":
        if state.hand is None:
            if state.can_check:
                return Recommendation("CHECK", "Checking is free while hero cards are unknown")
            return Recommendation("FOLD", "Hero cards are unknown; defaulting to fold")
        raise_count = sum(action.startswith("RAISE") for action in state.action_history)
        facing_raise = raise_count > 0 or (
            state.to_call is not None
            and state.big_blind is not None
            and state.to_call > state.big_blind
        )
        if not facing_raise:
            if state.can_check:
                return Recommendation("CHECK", f"Checking {state.hand} is free")
            opening_range = PREFLOP_OPEN_RANGES.get(state.hero_position)
            if opening_range is None:
                return Recommendation("NO_ACTION", "Hero position is unknown for an unopened pot")
            if state.hand in opening_range:
                return Recommendation("RAISE", f"Open {state.hand} from {state.hero_position}")
            return Recommendation("FOLD", f"{state.hand} is outside the {state.hero_position} opening range")
        if raise_count >= 2:
            if state.hand in PREFLOP_3BET_CONTINUE:
                priced = _priced_call(state, equity_samples)
                return replace(
                    priced,
                    reason=f"{state.hand} is in the conservative 3-bet continue range; {priced.reason}",
                )
            return Recommendation("FOLD", f"{state.hand} is outside the conservative 3-bet continue range")
        call_range = (
            PREFLOP_CALL_OPEN_IN_POSITION
            if state.hero_position in {"BTN", "CO"}
            else PREFLOP_CALL_OPEN
        )
        if state.hand in call_range:
            priced = _priced_call(state, equity_samples)
            return replace(
                priced,
                reason=f"{state.hand} is in the continue range; {priced.reason}",
            )
        if state.can_check:
            return Recommendation("CHECK", f"Checking {state.hand} is free")
        return Recommendation("FOLD", f"{state.hand} is outside the preflop continue range")

    if state.street in {"postflop", "flop", "turn", "river"}:
        if state.can_check:
            return Recommendation("CHECK", "Checking is free")
        return _priced_call(state, equity_samples)

    return Recommendation("NO_ACTION", "Street was not read reliably")


def with_vision_hand(
    state: ObservedState,
    cards: tuple[str | None, ...],
    board: tuple[str | None, ...] = (),
) -> ObservedState:
    """Replace text-derived cards with a verified two-card visual read."""
    if len(cards) != 2 or any(card is None for card in cards):
        return replace(state, hand=None, hero_cards=(), board_cards=())
    if any(card is None for card in board):
        return replace(state, hand=None, hero_cards=(), board_cards=())
    first, second = cards
    assert first is not None and second is not None
    confirmed_board = tuple(card for card in board if card is not None)
    rank_order = "23456789TJQKA"
    first_rank, first_suit = first[0].upper(), first[1].lower()
    second_rank, second_suit = second[0].upper(), second[1].lower()
    high, low = sorted((first_rank, second_rank), key=rank_order.index, reverse=True)
    if high == low:
        return replace(
            state,
            hand=high + low,
            hero_cards=(first, second),
            board_cards=confirmed_board,
        )
    suffix = "s" if first_suit == second_suit else "o"
    return replace(
        state,
        hand=high + low + suffix,
        hero_cards=(first, second),
        board_cards=confirmed_board,
    )
