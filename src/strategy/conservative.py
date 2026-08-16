"""A deliberately narrow first-pass poker policy.

It is designed for validation, not as a complete poker strategy. Ambiguous
state always yields NO_ACTION.
"""

from dataclasses import dataclass, replace


PREMIUM_PREFLOP = frozenset({"AA", "KK", "QQ", "JJ", "TT", "AKs", "AQs", "AKo"})


@dataclass(frozen=True)
class ObservedState:
    hand: str | None
    street: str | None
    to_call: float | None
    big_blind: float | None
    can_check: bool


@dataclass(frozen=True)
class Recommendation:
    action: str
    reason: str


def recommend(state: ObservedState, max_postflop_call_bb: float = 2) -> Recommendation:
    """Return a conservative decision without touching the browser."""
    if state.street == "preflop":
        if state.hand is None:
            if state.can_check:
                return Recommendation("CHECK", "Checking is free while hero cards are unknown")
            return Recommendation("FOLD", "Hero cards are unknown; defaulting to fold")
        if state.hand in PREMIUM_PREFLOP:
            if state.can_check:
                return Recommendation("CHECK", f"Checking premium hand {state.hand} is free")
            return Recommendation("CALL", f"Continue with premium preflop hand {state.hand}")
        if state.can_check:
            return Recommendation("CHECK", f"Checking {state.hand} is free")
        return Recommendation("FOLD", f"{state.hand} is outside the conservative preflop range")

    if state.street in {"postflop", "flop", "turn", "river"}:
        if state.can_check:
            return Recommendation("CHECK", "Checking is free")
        if state.to_call is None or state.big_blind is None:
            return Recommendation("NO_ACTION", "Call size or big blind is unknown")
        if state.to_call <= max_postflop_call_bb * state.big_blind:
            return Recommendation("CALL", f"Call is at most {max_postflop_call_bb} big blinds")
        return Recommendation("FOLD", "Call exceeds the conservative limit")

    return Recommendation("NO_ACTION", "Street was not read reliably")


def with_vision_hand(state: ObservedState, cards: tuple[str | None, ...]) -> ObservedState:
    """Replace text-derived cards with a verified two-card visual read."""
    if len(cards) != 2 or any(card is None for card in cards):
        return replace(state, hand=None)
    first, second = cards
    assert first is not None and second is not None
    rank_order = "23456789TJQKA"
    first_rank, first_suit = first[0].upper(), first[1].lower()
    second_rank, second_suit = second[0].upper(), second[1].lower()
    high, low = sorted((first_rank, second_rank), key=rank_order.index, reverse=True)
    if high == low:
        return replace(state, hand=high + low)
    suffix = "s" if first_suit == second_suit else "o"
    return replace(state, hand=high + low + suffix)
