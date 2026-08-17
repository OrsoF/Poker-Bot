from dataclasses import replace

import pytest

from src.browser import gambit
from src.browser.gambit import (
    CALL_LABEL,
    FOLD_LABEL,
    GAMBIT_URL,
    DecisionSnapshot,
    StableDecisionSnapshotDetector,
    _apply_action,
    _board_needs_screenshot_fallback,
    _flush_draw_call_reason,
    _six_max_position,
)


def _snapshot(**changes) -> DecisionSnapshot:
    snapshot = DecisionSnapshot(
        hero_turn=True,
        hero_cards=("As", "Kh"),
        board_cards=(),
        street="preflop",
        available_actions=frozenset({"FOLD", "CALL", "RAISE"}),
        call_amount=1.0,
        raise_amount=2.5,
        pot_amount=2.5,
        hero_stack=100.0,
        effective_stack=100.0,
        active_players=2,
        hero_position="BTN",
        action_history=(),
    )
    return replace(snapshot, **changes)


def test_gambit_url_uses_https() -> None:
    assert GAMBIT_URL.startswith("https://")


def test_fold_pattern_rejects_non_fold_actions() -> None:
    assert FOLD_LABEL.fullmatch("Fold")
    assert FOLD_LABEL.search("Fold (F)")
    assert not FOLD_LABEL.fullmatch("Call")


def test_call_pattern_accepts_gambit_chip_labels() -> None:
    assert CALL_LABEL.fullmatch("Call: 1.0 BB")
    assert CALL_LABEL.fullmatch("Call: 0.5 BB")
    assert CALL_LABEL.fullmatch("Call: 2")
    assert not CALL_LABEL.fullmatch("Raise: 2.0 BB")


def test_trailing_empty_board_slots_do_not_trigger_screenshot_card_matching() -> None:
    flop = ("first", "second", "third", None, None)
    turn = ("first", "second", "third", "fourth", None)
    assert not _board_needs_screenshot_fallback(flop)
    assert not _board_needs_screenshot_fallback(turn)


def test_missing_source_within_dealt_board_still_triggers_screenshot_validation() -> None:
    assert _board_needs_screenshot_fallback(("first", None, "third", None, None))
    assert _board_needs_screenshot_fallback((None, None, None, None, None))


def test_maps_six_max_seat_offsets_from_the_dealer_button() -> None:
    center = (0, 0)
    button = (0, -1)
    seats = ((0, -1), (0.87, -0.5), (0.87, 0.5), (0, 1), (-0.87, 0.5), (-0.87, -0.5))
    assert [_six_max_position(seat, button, center) for seat in seats] == ["BTN", "SB", "BB", "UTG", "HJ", "CO"]


def test_maps_flattened_gambit_layout_with_inward_dealer_chip() -> None:
    bounds = (280.0, 125.75, 900.0, 558.14)
    center = (730.0, 404.82)
    hero = (730.0, 596.0)

    upper_left_button = (433.0, 284.0)
    lower_left_button = (433.0, 424.0)

    assert _six_max_position(hero, upper_left_button, center, bounds) == "HJ"
    assert _six_max_position(hero, lower_left_button, center, bounds) == "CO"


def test_flush_draw_call_uses_pot_odds_when_the_pot_is_visible() -> None:
    assert _flush_draw_call_reason("flop", True, to_call=3, pot_bb=12, big_blind=1) is not None
    assert _flush_draw_call_reason("turn", False, to_call=6, pot_bb=12, big_blind=1) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"hero_turn": False},
        {"hero_cards": ("As", "Qh")},
        {"board_cards": ("2c", "3d", "4h")},
        {"street": "flop"},
        {"available_actions": frozenset({"FOLD", "CALL"})},
        {"call_amount": 2.0},
        {"raise_amount": 3.0},
        {"pot_amount": 3.5},
        {"hero_stack": 40.0},
        {"effective_stack": 40.0},
        {"active_players": 3},
        {"hero_position": "CO"},
        {"action_history": ("RAISE 3 BB",)},
    ],
)
def test_decision_snapshot_requires_identical_consecutive_frames(changes: dict) -> None:
    detector = StableDecisionSnapshotDetector()
    original = _snapshot()

    assert detector.observe(original) is None
    assert detector.observe(replace(original, **changes)) is None
    assert detector.observe(original) is None
    assert detector.observe(original) == original


def test_non_actionable_snapshot_resets_snapshot_stability() -> None:
    detector = StableDecisionSnapshotDetector()
    original = _snapshot()

    assert detector.observe(original) is None
    assert detector.observe(replace(original, hero_turn=False)) is None
    assert detector.observe(original) is None
    assert detector.observe(original) == original


class _Control:
    def __init__(self) -> None:
        self.clicks = 0

    def click(self, timeout: int) -> None:
        assert timeout == 2_000
        self.clicks += 1


def test_action_is_cancelled_when_fresh_snapshot_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _Control()
    expected = _snapshot()
    monkeypatch.setattr(gambit, "sleep", lambda _: None)
    monkeypatch.setattr(gambit, "_find_action_control", lambda page, action: control)

    applied = _apply_action(
        object(),
        "CALL",
        expected,
        lambda: replace(expected, call_amount=2.0),
    )

    assert not applied
    assert control.clicks == 0


def test_action_clicks_when_fresh_snapshot_is_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _Control()
    expected = _snapshot()
    monkeypatch.setattr(gambit, "sleep", lambda _: None)
    monkeypatch.setattr(gambit, "_find_action_control", lambda page, action: control)

    assert _apply_action(object(), "CALL", expected, lambda: expected)
    assert control.clicks == 1


def test_raise_is_cancelled_when_displayed_sizing_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _Control()
    expected = _snapshot()
    monkeypatch.setattr(gambit, "sleep", lambda _: None)
    monkeypatch.setattr(gambit, "_find_action_control", lambda page, action: control)

    applied = _apply_action(
        object(),
        "RAISE",
        expected,
        lambda: replace(expected, raise_amount=3.0),
    )

    assert not applied
    assert control.clicks == 0


def test_raise_clicks_when_displayed_sizing_is_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _Control()
    expected = _snapshot()
    monkeypatch.setattr(gambit, "sleep", lambda _: None)
    monkeypatch.setattr(gambit, "_find_action_control", lambda page, action: control)

    assert _apply_action(object(), "RAISE", expected, lambda: expected)
    assert control.clicks == 1
