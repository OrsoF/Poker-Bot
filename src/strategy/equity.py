"""Deterministic showdown-equity and price checks for conservative calls."""

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from random import Random

from src.strategy.hand_strength import RANKS, evaluate_hand


SUITS = "shdc"
DECK = tuple(f"{rank}{suit}" for rank in RANKS for suit in SUITS)


@dataclass(frozen=True)
class BoardTexture:
    paired: bool
    flush_pressure: bool
    connected: bool

    @property
    def wet(self) -> bool:
        return sum((self.paired, self.flush_pressure, self.connected)) >= 2

    @property
    def label(self) -> str:
        features = [
            label
            for enabled, label in (
                (self.paired, "paired"),
                (self.flush_pressure, "flush-heavy"),
                (self.connected, "connected"),
            )
            if enabled
        ]
        return "/".join(features) if features else "dry"


@dataclass(frozen=True)
class CallAssessment:
    should_call: bool
    reason: str
    equity: float | None = None
    pot_odds: float | None = None
    required_equity: float | None = None


def board_texture(board: tuple[str, ...]) -> BoardTexture:
    ranks = Counter(card[0].upper() for card in board)
    suits = Counter(card[1].lower() for card in board)
    rank_values = {RANKS.index(rank) + 2 for rank in ranks}
    if 14 in rank_values:
        rank_values.add(1)
    connected = any(
        len(rank_values.intersection(range(low, low + 5))) >= 3
        for low in range(1, 11)
    )
    return BoardTexture(
        paired=any(count >= 2 for count in ranks.values()),
        flush_pressure=max(suits.values(), default=0) >= 3,
        connected=connected,
    )


def hole_cards_improve_board(hero: tuple[str, ...], board: tuple[str, ...]) -> bool:
    """Require a made-hand or one-card-draw contribution from a hole card."""
    if len(hero) != 2 or len(board) not in {3, 4, 5} or not _valid_unique((*hero, *board)):
        return False

    board_ranks = Counter(card[0].upper() for card in board)
    combined_ranks = Counter(card[0].upper() for card in (*hero, *board))
    if any(
        combined_ranks[card[0].upper()] >= 2
        and combined_ranks[card[0].upper()] > board_ranks[card[0].upper()]
        for card in hero
    ):
        return True

    board_suits = Counter(card[1].lower() for card in board)
    combined_suits = Counter(card[1].lower() for card in (*hero, *board))
    if any(
        combined_suits[card[1].lower()] >= 4
        and combined_suits[card[1].lower()] > board_suits[card[1].lower()]
        for card in hero
    ):
        return True

    board_values = _rank_values(board)
    combined_values = _rank_values((*hero, *board))
    hero_values = _rank_values(hero)
    for low in range(1, 11):
        window = set(range(low, low + 5))
        if (
            len(combined_values & window) >= 4
            and len(combined_values & window) > len(board_values & window)
            and bool(hero_values & window)
        ):
            return True

    if len(board) == 5:
        hero_hand = evaluate_hand(hero, board)
        board_hand = evaluate_hand((board[0], board[1]), board[2:])
        return (
            hero_hand is not None
            and board_hand is not None
            and hero_hand.score > board_hand.score
        )
    return False


@lru_cache(maxsize=512)
def estimate_showdown_equity(
    hero: tuple[str, ...],
    board: tuple[str, ...],
    opponents: int,
    samples: int = 1_200,
) -> float | None:
    """Estimate equity against random legal holdings with deterministic sampling."""
    known = (*hero, *board)
    if (
        len(hero) != 2
        or len(board) not in {0, 3, 4, 5}
        or opponents < 1
        or samples < 1
        or not _valid_unique(known)
    ):
        return None
    remaining = tuple(card for card in DECK if card not in known)
    missing_board = 5 - len(board)
    needed = missing_board + 2 * opponents
    if needed > len(remaining):
        return None

    seed_text = "|".join((*hero, *board, str(opponents), str(samples)))
    rng = Random(int.from_bytes(sha256(seed_text.encode("ascii")).digest()[:8], "big"))
    equity = 0.0
    completed = 0
    for _ in range(samples):
        drawn = rng.sample(remaining, needed)
        runout = tuple((*board, *drawn[:missing_board]))
        hero_hand = evaluate_hand(hero, runout)
        if hero_hand is None:
            continue
        scores = [hero_hand.score]
        offset = missing_board
        for opponent in range(opponents):
            cards = tuple(drawn[offset + 2 * opponent:offset + 2 * opponent + 2])
            opponent_hand = evaluate_hand(cards, runout)
            if opponent_hand is None:
                break
            scores.append(opponent_hand.score)
        if len(scores) != opponents + 1:
            continue
        best = max(scores)
        winners = sum(score == best for score in scores)
        if scores[0] == best:
            equity += 1 / winners
        completed += 1
    return equity / completed if completed else None


def assess_call(
    *,
    hero: tuple[str, ...],
    board: tuple[str, ...],
    to_call: float | None,
    pot: float | None,
    effective_stack: float | None,
    active_players: int | None,
    samples: int = 1_200,
) -> CallAssessment:
    """Compare conservative estimated equity with price and stack-sensitive odds."""
    if to_call is None or to_call <= 0:
        return CallAssessment(False, "Call price is unavailable")
    if pot is None or pot <= 0:
        return CallAssessment(False, "Pot size is unavailable")
    if effective_stack is None or effective_stack <= 0:
        return CallAssessment(False, "Effective stack is unavailable")
    if active_players is None or active_players < 2:
        return CallAssessment(False, "Active player count is unavailable")
    if to_call > effective_stack:
        return CallAssessment(False, "Call exceeds the effective stack")
    if board and not hole_cards_improve_board(hero, board):
        return CallAssessment(False, "Hole cards do not improve the board or a confirmed draw")

    opponents = active_players - 1
    showdown_equity = estimate_showdown_equity(hero, board, opponents, samples=samples)
    if showdown_equity is None:
        return CallAssessment(False, "Equity could not be estimated from the confirmed cards")

    pot_odds = to_call / (pot + to_call)
    stack_fraction = to_call / effective_stack
    texture = board_texture(board)
    margin = 0.05 + 0.01 * max(0, opponents - 1)
    if stack_fraction >= 0.5:
        margin += 0.04
    elif stack_fraction >= 0.25:
        margin += 0.02
    if board and texture.wet:
        margin += 0.02
    required = min(0.95, pot_odds + margin)
    realization = 1.0
    if len(board) < 5 and stack_fraction < 0.8:
        realization = 0.82 if len(board) <= 3 else 0.90
        realization -= 0.03 * max(0, opponents - 1)
        if texture.wet:
            realization -= 0.03
        realization = max(0.60, realization)
    equity = showdown_equity * realization
    bet_fraction = to_call / pot
    reason = (
        f"usable equity {equity:.0%} ({showdown_equity:.0%} showdown) vs "
        f"{pot_odds:.0%} pot odds/{required:.0%} conservative threshold; "
        f"call {bet_fraction:.0%} pot, {stack_fraction:.0%} effective stack, "
        f"{opponents} opponent{'s' if opponents != 1 else ''}, {texture.label} board"
    )
    return CallAssessment(
        equity >= required,
        reason,
        equity=equity,
        pot_odds=pot_odds,
        required_equity=required,
    )


def _rank_values(cards: tuple[str, ...]) -> set[int]:
    values = {RANKS.index(card[0].upper()) + 2 for card in cards}
    if 14 in values:
        values.add(1)
    return values


def _valid_unique(cards: tuple[str, ...]) -> bool:
    return (
        len(set(cards)) == len(cards)
        and all(
            len(card) == 2
            and card[0].upper() in RANKS
            and card[1].lower() in SUITS
            for card in cards
        )
    )
