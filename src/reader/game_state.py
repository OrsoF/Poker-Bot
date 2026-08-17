"""Conservative parser for facts that are visible in Gambit's page text."""

import re

from src.strategy.conservative import ObservedState


HAND_PATTERN = re.compile(
    r"\b(10|Jack|Queen|King|Ace|[2-9])-(10|Jack|Queen|King|Ace|[2-9])\s+(suited|offsuit)\b",
    re.IGNORECASE,
)
CALL_PATTERN = re.compile(r"\bCall:\s*(\d+(?:\.\d+)?)\s*(?:BB)?\b", re.IGNORECASE)
HERO_STACK_PATTERN = re.compile(
    r"(?:\b(\d+(?:\.\d+)?)\s*BB\s+ACTION\b|\bACTION\s+(\d+(?:\.\d+)?)\s*BB\b)",
    re.IGNORECASE,
)
RAISE_ACTION_PATTERN = re.compile(r"\bRAISE\s+(\d+(?:\.\d+)?)\s*BB\b")
RAISE_CONTROL_PATTERN = re.compile(r"\bRaise:\s*(\d+(?:\.\d+)?)\s*(?:BB)?\b", re.IGNORECASE)
POT_PATTERN = re.compile(r"\bPot:\s*(\d+(?:\.\d+)?)\s*(?:BB)?\b", re.IGNORECASE)
SEAT_ACTION_PATTERN = re.compile(r"\b(?:FOLD|RAISE\s+\d+(?:\.\d+)?\s*BB|CALL\s+\d+(?:\.\d+)?\s*BB|CHECK)\b")
OPPONENT_SEAT_PATTERN = re.compile(
    r"\b[A-Z][a-z]+\s+(\d+(?:\.\d+)?)\s*BB(?:\s+(FOLD|RAISE\s+\d+(?:\.\d+)?\s*BB|CALL\s+\d+(?:\.\d+)?\s*BB|CHECK))?"
)
SEATED_PLAYERS = 6
POSTFLOP_SIZING_PATTERN = re.compile(r"\b1/3\s+1/2\s+3/4\s+Pot\b", re.IGNORECASE)
PREFLOP_SIZING_PATTERN = re.compile(r"\b2x\s+2\.5x\s+3x\s+4x\b", re.IGNORECASE)
CHECK_CONTROL_PATTERN = re.compile(r"\bCheck\s+(?:Bet|Raise):\s*\d+\b", re.IGNORECASE)
RANKS = {"ace": "A", "king": "K", "queen": "Q", "jack": "J", "10": "T"}
HERO_PROMPT_PATTERN = re.compile(
    r"\b(?:offsuit|suited|to you|checked around|bet into you|your draw|you picked up)\b",
    re.IGNORECASE,
)


def _normalize_rank(rank: str) -> str:
    return RANKS.get(rank.lower(), rank)


def _parse_hand(text: str) -> str | None:
    match = HAND_PATTERN.search(text)
    if match is None:
        return None
    first, second, suitedness = match.groups()
    cards = sorted((_normalize_rank(first), _normalize_rank(second)), key="23456789TJQKA".index, reverse=True)
    return "".join(cards) + ("s" if suitedness.lower() == "suited" else "o")


def parse_visible_state(
    text: str,
    big_blind: float = 1,
    read_coaching_hand: bool = True,
) -> ObservedState:
    """Parse only explicit facts and Gambit's visible action-panel variants."""
    lowered = text.lower()
    hand = _parse_hand(text) if read_coaching_hand else None
    street = "preflop" if hand is not None else None
    if PREFLOP_SIZING_PATTERN.search(text):
        street = "preflop"
    for candidate in ("flop", "turn", "river"):
        if re.search(rf"\b{candidate}\b", lowered):
            street = candidate
            break
    if POSTFLOP_SIZING_PATTERN.search(text):
        # Gambit does not render the literal street name in its text view, but
        # its post-flop action panel consistently replaces preflop x-sizing
        # with pot-fraction sizing controls.
        street = "postflop"
    call_match = CALL_PATTERN.search(text)
    hero_stack_match = HERO_STACK_PATTERN.search(text)
    pot_match = POT_PATTERN.search(text)
    raise_actions = RAISE_ACTION_PATTERN.findall(text)
    raise_control_match = RAISE_CONTROL_PATTERN.search(text)
    action_history = tuple(match.group(0) for match in SEAT_ACTION_PATTERN.finditer(text))
    folded_players = sum(action == "FOLD" for action in action_history)
    opponent_seats = OPPONENT_SEAT_PATTERN.findall(text)
    active_opponent_stacks = [float(stack) for stack, action in opponent_seats if action != "FOLD"]
    effective_stack = None
    if hero_stack_match and len(opponent_seats) == SEATED_PLAYERS - 1 and active_opponent_stacks:
        hero_stack = float(next(value for value in hero_stack_match.groups() if value is not None))
        effective_stack = min(hero_stack, *active_opponent_stacks)
    return ObservedState(
        hand=hand,
        street=street,
        to_call=float(call_match.group(1)) if call_match else None,
        big_blind=big_blind,
        can_check=bool(CHECK_CONTROL_PATTERN.search(text)),
        hero_stack_bb=float(next(value for value in hero_stack_match.groups() if value is not None)) if hero_stack_match else None,
        pot_bb=float(pot_match.group(1)) if pot_match else None,
        current_raise_to_bb=float(raise_actions[-1]) if raise_actions else None,
        minimum_raise_to_bb=float(raise_control_match.group(1)) if raise_control_match else None,
        active_players=SEATED_PLAYERS - folded_players if hero_stack_match else None,
        effective_stack_bb=effective_stack,
        action_history=action_history,
    )


def has_live_action_panel(text: str) -> bool:
    """Require Gambit's active table controls and reject a completed hand."""
    return (
        "All-In" in text
        and "Next Hand" not in text
        and "Session Complete" not in text
        and ("Fold" in text or "Check" in text or "Call:" in text)
    )
