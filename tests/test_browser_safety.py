from dataclasses import replace

import pytest

from src.browser import gambit, gambit_observation
from src.browser.gambit import _apply_action
from src.browser.gambit_observation import (
    GambitTableReader,
    HeroTurnScreenshotCache,
    StableObservationDetector,
    TableObservation,
    _needs_screenshot,
)
from src.reader.game_state import parse_visible_state
from src.strategy.conservative import Recommendation


def _observation(**changes) -> TableObservation:
    snapshot = TableObservation(
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
        raw_text="",
        parsed_state=parse_visible_state(""),
        hero_reads=(),
        board_reads=(),
        hero_sources=(),
        board_sources=(),
        screenshot=None,
    )
    return replace(snapshot, **changes)


class _Control:
    def __init__(self) -> None:
        self.clicks = 0

    def click(self, timeout: int) -> None:
        assert timeout == 2_000
        self.clicks += 1


class _CapturePage:
    def __init__(self) -> None:
        self.captures = 0

    def screenshot(self) -> bytes:
        self.captures += 1
        return b"screenshot"


class _VisionReader:
    def read_screenshot(self, screenshot: bytes) -> object:
        assert screenshot == b"screenshot"
        return object()


def test_atomic_snapshot_and_action_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _observation()
    detector = StableObservationDetector()

    assert detector.observe(snapshot) is None
    assert detector.observe(replace(snapshot, raw_text="rendered differently")) == snapshot
    assert detector.observe(replace(snapshot, call_amount=2.0)) is None
    assert detector.observe(snapshot) is None
    assert detector.observe(snapshot) == snapshot

    assert not _needs_screenshot(False, False, (None, None, None, None, None))
    assert _needs_screenshot(True, False, (None, None, None, None, None))
    assert not _needs_screenshot(True, True, ("a", "b", "c", None, None))
    assert _needs_screenshot(True, True, ("a", None, "c", None, None))

    capture_page = _CapturePage()
    capture_cache = HeroTurnScreenshotCache()
    vision_reader = _VisionReader()
    assert capture_cache.read(capture_page, vision_reader, ("preflop",))
    assert capture_cache.read(capture_page, vision_reader, ("preflop",))
    assert capture_page.captures == 1
    assert capture_cache.read(capture_page, vision_reader, ("flop",))
    assert capture_page.captures == 2
    capture_cache.reset()
    assert capture_cache.read(capture_page, vision_reader, ("flop",))
    assert capture_page.captures == 3

    reads = []
    monkeypatch.setattr(
        gambit_observation,
        "read_table_observation",
        lambda page, vision, matcher, stage, cache: reads.append(stage) or snapshot,
    )
    reader = GambitTableReader("page", "vision", "matcher", "stable-stage")
    assert reader.read() == snapshot
    assert reader.read(stabilize_stage=False) == snapshot
    assert reads == ["stable-stage", None]

    control = _Control()
    monkeypatch.setattr(gambit, "sleep", lambda _: None)
    monkeypatch.setattr(gambit, "_find_action_control", lambda page, action: control)
    decision = Recommendation("CALL", "priced call", amount=1.0)

    assert _apply_action(object(), decision, snapshot, lambda: snapshot)
    assert control.clicks == 1
    assert not _apply_action(
        object(), decision, snapshot, lambda: replace(snapshot, call_amount=2.0)
    )
    assert control.clicks == 1
