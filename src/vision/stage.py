"""Conservative street detection from stable board-card observations."""

from dataclasses import dataclass

from src.vision.cards import CardRead


STREETS = ("preflop", "flop", "turn", "river")
_COUNTS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


def stage_from_board(board: tuple[CardRead, ...]) -> str | None:
    """Map five unambiguous board slots to a street; unknown reads stay unknown."""
    if len(board) != 5:
        return None
    dealt = [read for read in board if not read.is_empty]
    if any(read.card is None for read in dealt):
        return None
    if any(not read.is_empty for read in board[len(dealt):]):
        return None
    return _COUNTS.get(len(dealt))


@dataclass
class StableStageDetector:
    """Accept a forward-only street after it appears in two consecutive frames."""

    candidate: str | None = None
    candidate_frames: int = 0
    stage: str | None = None

    def reset(self) -> None:
        """Forget the completed hand before observing the next one."""
        self.candidate = None
        self.candidate_frames = 0
        self.stage = None

    def observe(self, board: tuple[CardRead, ...]) -> str | None:
        observed = stage_from_board(board)
        if observed is None:
            self.candidate = None
            self.candidate_frames = 0
            return None
        if observed == self.candidate:
            self.candidate_frames += 1
        else:
            self.candidate = observed
            self.candidate_frames = 1
        if self.candidate_frames < 2:
            return None
        if self.stage is not None and STREETS.index(observed) < STREETS.index(self.stage):
            return None
        self.stage = observed
        return self.stage
