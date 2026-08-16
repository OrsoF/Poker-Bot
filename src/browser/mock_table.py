from src.strategy.models import Action, TableState


class MockTable:
    """Offline adapter used while developing strategy safely."""

    def read_state(self) -> TableState:
        return TableState(to_call=0, minimum_raise=2, stack=100)

    def perform(self, action: Action) -> None:
        print(f"[dry run] would perform: {action}")
