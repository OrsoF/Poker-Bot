"""Small, dependency-free evaluator for the best made Hold'em hand."""

from collections import Counter
from dataclasses import dataclass
from itertools import combinations


RANKS = "23456789TJQKA"
RANK_VALUE = {rank: index + 2 for index, rank in enumerate(RANKS)}
RANK_NAMES = {
    "2": "twos", "3": "threes", "4": "fours", "5": "fives", "6": "sixes",
    "7": "sevens", "8": "eights", "9": "nines", "T": "tens", "J": "jacks",
    "Q": "queens", "K": "kings", "A": "aces",
}


@dataclass(frozen=True)
class HandStrength:
    category: str
    detail: str
    score: tuple[int, ...]

    @property
    def text(self) -> str:
        return f"{self.category} — {self.detail}"


@dataclass(frozen=True)
class DrawInfo:
    """Confirmed one-card draws available before the river."""

    flush_draw_suit: str | None = None
    nut_flush_draw: bool = False

    @property
    def has_flush_draw(self) -> bool:
        return self.flush_draw_suit is not None


def flush_draw_equity(street: str | None, nut_flush_draw: bool) -> float | None:
    """Conservative all-in equity estimates for a one-card flush draw.

    Non-nut draws are discounted for dominated flushes and paired-board cases.
    They are intentionally suitable only as a pot-odds gate, not as a solver.
    """
    estimates = {
        "flop": (0.35, 0.31),
        "turn": (0.196, 0.17),
    }
    values = estimates.get(street)
    if values is None:
        return None
    return values[0] if nut_flush_draw else values[1]


def evaluate_hand(hero: tuple[str | None, ...], board: tuple[str | None, ...]) -> HandStrength | None:
    """Return the best made hand for a complete flop, turn, or river reading."""
    cards = tuple((*hero, *board))
    if len(hero) != 2 or len(board) not in {3, 4, 5} or any(card is None for card in cards):
        return None
    normalized = tuple(card for card in cards if card is not None)
    if len(set(normalized)) != len(normalized) or any(_invalid(card) for card in normalized):
        return None
    return max((_evaluate_five(combo) for combo in combinations(normalized, 5)), key=lambda hand: hand.score)


def analyze_draws(hero: tuple[str | None, ...], board: tuple[str | None, ...]) -> DrawInfo | None:
    """Identify fully confirmed flop/turn draws; never infer from missing cards."""
    cards = tuple((*hero, *board))
    if len(hero) != 2 or len(board) not in {3, 4} or any(card is None for card in cards):
        return None
    normalized = tuple(card for card in cards if card is not None)
    if len(set(normalized)) != len(normalized) or any(_invalid(card) for card in normalized):
        return None
    suits = Counter(card[1].lower() for card in normalized)
    draw_suit = next((suit for suit, count in suits.items() if count == 4), None)
    if draw_suit is None:
        return DrawInfo()
    return DrawInfo(
        flush_draw_suit=draw_suit,
        nut_flush_draw=any(card[0].upper() == "A" and card[1].lower() == draw_suit for card in hero),
    )


def _invalid(card: str) -> bool:
    return len(card) != 2 or card[0].upper() not in RANKS or card[1].lower() not in "shdc"


def _evaluate_five(cards: tuple[str, ...]) -> HandStrength:
    ranks = sorted((RANK_VALUE[card[0].upper()] for card in cards), reverse=True)
    counts = Counter(ranks)
    grouped = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    flush = len({card[1].lower() for card in cards}) == 1
    straight_high = _straight_high(set(ranks))

    if flush and straight_high:
        return _hand("Straight flush", f"{_name(straight_high)} high", (8, straight_high))
    if grouped[0][0] == 4:
        quad = grouped[0][1]
        kicker = max(rank for rank in ranks if rank != quad)
        return _hand("Four of a kind", _name(quad), (7, quad, kicker))
    if grouped[0][0] == 3 and grouped[1][0] == 2:
        return _hand("Full house", f"{_name(grouped[0][1])} over {_name(grouped[1][1])}", (6, grouped[0][1], grouped[1][1]))
    if flush:
        return _hand("Flush", f"{_name(ranks[0])} high", (5, *ranks))
    if straight_high:
        return _hand("Straight", f"{_name(straight_high)} high", (4, straight_high))
    if grouped[0][0] == 3:
        trip = grouped[0][1]
        kickers = sorted((rank for rank in ranks if rank != trip), reverse=True)
        return _hand("Three of a kind", _name(trip), (3, trip, *kickers))
    pairs = sorted((rank for count, rank in grouped if count == 2), reverse=True)
    if len(pairs) == 2:
        kicker = max(rank for rank in ranks if rank not in pairs)
        return _hand("Two pair", f"{_name(pairs[0])} and {_name(pairs[1])}", (2, *pairs, kicker))
    if len(pairs) == 1:
        pair = pairs[0]
        kickers = sorted((rank for rank in ranks if rank != pair), reverse=True)
        return _hand("Pair", _name(pair), (1, pair, *kickers))
    return _hand("High card", _name(ranks[0]), (0, *ranks))


def _straight_high(ranks: set[int]) -> int | None:
    if {14, 2, 3, 4, 5}.issubset(ranks):
        return 5
    for high in range(14, 5 - 1, -1):
        if set(range(high - 4, high + 1)).issubset(ranks):
            return high
    return None


def _name(rank: int) -> str:
    return RANK_NAMES[RANKS[rank - 2]]


def _hand(category: str, detail: str, score: tuple[int, ...]) -> HandStrength:
    return HandStrength(category=category, detail=detail, score=score)
