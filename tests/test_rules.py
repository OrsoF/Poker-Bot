from src.strategy.models import TableState
from src.strategy.rules import choose_action


def test_checks_when_nothing_is_owed() -> None:
    state = TableState(to_call=0, minimum_raise=2, stack=100)
    assert choose_action(state).kind == "check"
