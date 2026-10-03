"""Opt-in preflop all-in policy with its own expanded hand range."""

from math import isfinite

from src.models import ObservedState
from src.strategy.conservative import Recommendation


ALL_IN_HANDS = frozenset({
    "55", "66", "77", "88", "99", "TT", "JJ", "QQ", "KK", "AA",
    "A2s", "A3s", "A4s", "A5s", "A6s", "A7s", "A8s", "A9s", "ATs", "AJs", "AQs", "AKs",
    "KTs", "KJs", "KQs", "QTs", "QJs", "JTs",
    "ATo", "AJo", "AQo", "AKo", "KJo", "KQo",
})


def decide(state: ObservedState) -> Recommendation:
    """Push the selected range preflop, regardless of position or prior raises."""
    if (
        state.street == "preflop"
        and state.hand in ALL_IN_HANDS
        and len(state.hero_cards) == 2
        and all(card is not None for card in state.hero_cards)
        and len(set(state.hero_cards)) == 2
        and not state.board_cards
    ):
        if (
            {"ALL_IN", "RAISE"} <= state.available_actions
            and state.raise_amount is not None
            and isfinite(state.raise_amount)
            and state.raise_amount > 0
        ):
            return Recommendation("ALL_IN", f"Preflop all-in with {state.hand}")
        reason = "All-in sizing or raise amount is unavailable"
        if "CHECK" in state.available_actions:
            return Recommendation("CHECK", f"{reason}; checking is free")
        return Recommendation("NO_ACTION", f"{reason}; waiting for confirmed sizing")
    else:
        reason = "All-in requires confirmed preflop cards in the selected range"
    if "CHECK" in state.available_actions:
        return Recommendation("CHECK", f"{reason}; checking is free")
    if "FOLD" in state.available_actions:
        return Recommendation("FOLD", f"{reason}; fail-safe fold")
    return Recommendation("NO_ACTION", f"{reason}; action is unavailable")
