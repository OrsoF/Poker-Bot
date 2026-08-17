from src.strategy.equity import (
    assess_call,
    board_texture,
    estimate_showdown_equity,
    hole_cards_improve_board,
)


def test_strong_hand_calls_when_equity_clears_price() -> None:
    assessment = assess_call(
        hero=("Ah", "Ad"),
        board=("As", "7c", "2h"),
        to_call=2,
        pot=10,
        effective_stack=100,
        active_players=2,
        samples=400,
    )
    assert assessment.should_call
    assert assessment.equity is not None
    assert assessment.required_equity is not None
    assert assessment.equity > assessment.required_equity


def test_same_draw_folds_when_bet_is_too_expensive() -> None:
    common = {
        "hero": ("Ah", "Kh"),
        "board": ("Qh", "Jh", "2c"),
        "pot": 10,
        "effective_stack": 100,
        "active_players": 2,
        "samples": 500,
    }
    assert assess_call(to_call=2, **common).should_call
    assert not assess_call(to_call=30, **common).should_call


def test_board_only_pair_is_not_treated_as_a_hero_hand() -> None:
    assessment = assess_call(
        hero=("9h", "8d"),
        board=("As", "Ac", "Kc"),
        to_call=1,
        pot=20,
        effective_stack=100,
        active_players=2,
        samples=200,
    )
    assert not hole_cards_improve_board(("9h", "8d"), ("As", "Ac", "Kc"))
    assert not assessment.should_call
    assert "Hole cards" in assessment.reason


def test_multiway_equity_is_lower_than_heads_up_equity() -> None:
    heads_up = estimate_showdown_equity(("Ah", "Ad"), (), opponents=1, samples=600)
    multiway = estimate_showdown_equity(("Ah", "Ad"), (), opponents=4, samples=600)
    assert heads_up is not None and multiway is not None
    assert multiway < heads_up


def test_effective_stack_and_player_count_are_required() -> None:
    common = {
        "hero": ("Ah", "Ad"),
        "board": ("As", "7c", "2h"),
        "to_call": 2,
        "pot": 10,
        "samples": 100,
    }
    assert not assess_call(effective_stack=None, active_players=2, **common).should_call
    assert not assess_call(effective_stack=100, active_players=None, **common).should_call
    assert not assess_call(effective_stack=1, active_players=2, **common).should_call


def test_board_texture_reports_paired_flush_heavy_connected_board() -> None:
    texture = board_texture(("9h", "8h", "7h", "9c"))
    assert texture.paired
    assert texture.flush_pressure
    assert texture.connected
    assert texture.wet
