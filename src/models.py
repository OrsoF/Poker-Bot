"""Immutable poker facts shared by readers, recording, and strategy."""

from dataclasses import dataclass


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
