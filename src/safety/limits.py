from src.strategy.models import Action


class Limits:
    def __init__(self, max_hands: int, stop_loss: int) -> None:
        self.max_hands = max_hands
        self.stop_loss = stop_loss
        self.hands_played = 0

    def allows(self, action: Action) -> bool:
        """Expand this with session counters and explicit user confirmation."""
        return self.hands_played < self.max_hands and self.stop_loss >= 0
