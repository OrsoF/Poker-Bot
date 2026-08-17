"""A deliberately narrow first-pass poker policy.

It is designed for validation, not as a complete poker strategy. Ambiguous
state always yields NO_ACTION.
"""

from dataclasses import dataclass, replace

from src.strategy.equity import assess_call
from src.strategy.hand_strength import evaluate_hand


from src.strategy.preflop_ranges import (
    PREFLOP_3BET_CONTINUE,
    PREFLOP_CALL_OPEN,
    PREFLOP_CALL_OPEN_IN_POSITION,
    PREFLOP_OPEN_RANGES,
)


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
            return Recommendation(
                "FOLD",
                f"{state.hand} is outside the {state.hero_position} opening range",
            )
        if raise_count >= 2:
            if state.hand in PREFLOP_3BET_CONTINUE:
                priced = _priced_call(state, equity_samples)
                return replace(
                    priced,
                    reason=f"{state.hand} is in the conservative 3-bet continue range; {priced.reason}",
                )
            return Recommendation(
                "FOLD",
                f"{state.hand} is outside the conservative 3-bet continue range",
            )
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


def decide(state: ObservedState, equity_samples: int = 1_200) -> Recommendation:
    """Return one final, legal, executable decision with its exact amount."""
    decision = recommend(state, equity_samples=equity_samples)

    if state.street in {"flop", "turn", "river"} and state.can_check:
        strength = evaluate_hand(state.hero_cards, state.board_cards)
        has_made_hand = strength is not None and strength.score[0] >= 1
        decision = Recommendation(
            "RAISE" if has_made_hand else "CHECK",
            strength.text if has_made_hand else "No made hand; check for free",
        )

    if decision.action not in state.available_actions:
        decision = Recommendation(
            "NO_ACTION",
            f"{decision.reason}; recommended action is unavailable",
        )

    if decision.action == "CALL":
        if state.to_call is None:
            decision = Recommendation("NO_ACTION", f"{decision.reason}; call amount is unavailable")
        else:
            decision = replace(decision, amount=state.to_call)
    elif decision.action == "RAISE":
        if state.raise_amount is None:
            decision = Recommendation("NO_ACTION", f"{decision.reason}; raise amount is unavailable")
        else:
            decision = replace(decision, amount=state.raise_amount)

    if decision.action == "NO_ACTION":
        if "CHECK" in state.available_actions:
            return Recommendation("CHECK", f"{decision.reason}; checking is free")
        if "FOLD" in state.available_actions:
            return Recommendation("FOLD", f"{decision.reason}; fail-safe fold")
    return decision


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
