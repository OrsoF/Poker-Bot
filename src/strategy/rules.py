from src.strategy.models import Action, TableState


def choose_action(state: TableState) -> Action:
    """Temporary deterministic policy; replace with tested poker logic."""
    if state.to_call == 0:
        return Action("check")
    return Action("fold")
