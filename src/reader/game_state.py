"""Conservative parser for facts that are visible in Gambit's page text."""

import re

from src.strategy.conservative import ObservedState


HAND_PATTERN = re.compile(
    r"\b(10|Jack|Queen|King|Ace|[2-9])-(10|Jack|Queen|King|Ace|[2-9])\s+(suited|offsuit)\b",
    re.IGNORECASE,
)
CALL_PATTERN = re.compile(r"\bCall:\s*(\d+(?:\.\d+)?)\s*(?:BB)?\b", re.IGNORECASE)
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
    return ObservedState(
        hand=hand,
        street=street,
        to_call=float(call_match.group(1)) if call_match else None,
        big_blind=big_blind,
        can_check=bool(CHECK_CONTROL_PATTERN.search(text)),
    )


def has_live_action_panel(text: str) -> bool:
    """Require Gambit's active table controls and reject a completed hand."""
    return (
        "All-In" in text
        and "Next Hand" not in text
        and "Session Complete" not in text
        and ("Fold" in text or "Check" in text or "Call:" in text)
    )
