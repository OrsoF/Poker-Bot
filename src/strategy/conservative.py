"""One deliberately strict, fail-safe poker policy.

The policy acts only on a confirmed, unopened preflop hand. It never calls,
never 3-bets, and never bets postflop. Unknown or incomplete information folds
unless checking is free.
"""

from dataclasses import dataclass, replace


SAFE_OPEN_HANDS = frozenset({"AA", "KK", "QQ", "JJ", "AKs", "AQs", "AKo"})
OPEN_POSITIONS = frozenset({"UTG", "HJ", "CO", "BTN", "SB"})


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
    available_actions: frozenset[str] = frozenset()
    raise_amount: float | None = None


@dataclass(frozen=True)
class Recommendation:
    action: str
    reason: str
    amount: float | None = None


def recommend(state: ObservedState) -> Recommendation:
    """Choose the safest action without touching the browser."""
    if state.can_check:
        return Recommendation("CHECK", "Checking is free")
    if state.street != "preflop":
        return Recommendation("FOLD", "Postflop betting is disabled in the safe strategy")
    if state.hand is None:
        return Recommendation("FOLD", "Hero cards are unknown")
    if state.hero_position not in OPEN_POSITIONS:
        return Recommendation("FOLD", "Hero position is unknown or unsupported")
    facing_raise = any(action.startswith("RAISE") for action in state.action_history) or (
        state.to_call is not None
        and state.big_blind is not None
        and state.to_call > state.big_blind
    )
    if facing_raise:
        return Recommendation("FOLD", "Calling and re-raising are disabled in the safe strategy")
    if state.hand in SAFE_OPEN_HANDS:
        return Recommendation("RAISE", f"Open {state.hand} from {state.hero_position}")
    return Recommendation("FOLD", f"{state.hand} is outside the safe opening range")


def decide(state: ObservedState) -> Recommendation:
    """Return one legal action and its exact displayed amount."""
    recommendation = recommend(state)
    if recommendation.action == "RAISE" and state.raise_amount is not None:
        recommendation = replace(recommendation, amount=state.raise_amount)
    elif recommendation.action == "RAISE":
        recommendation = Recommendation("NO_ACTION", "Raise amount is unavailable")

    if recommendation.action in state.available_actions:
        return recommendation
    if "CHECK" in state.available_actions:
        return Recommendation("CHECK", f"{recommendation.reason}; checking is free")
    if "FOLD" in state.available_actions:
        return Recommendation("FOLD", f"{recommendation.reason}; fail-safe fold")
    return Recommendation("NO_ACTION", f"{recommendation.reason}; action is unavailable")


def with_vision_hand(
    state: ObservedState,
    cards: tuple[str | None, ...],
    board: tuple[str | None, ...] = (),
) -> ObservedState:
    """Replace text-derived cards with a verified two-card visual read."""
    if len(cards) != 2 or any(card is None for card in cards) or any(card is None for card in board):
        return replace(state, hand=None, hero_cards=(), board_cards=())
    first, second = cards
    assert first is not None and second is not None
    rank_order = "23456789TJQKA"
    high, low = sorted((first[0].upper(), second[0].upper()), key=rank_order.index, reverse=True)
    hand = high + low if high == low else high + low + ("s" if first[1] == second[1] else "o")
    return replace(
        state,
        hand=hand,
        hero_cards=(first, second),
        board_cards=tuple(card for card in board if card is not None),
    )
