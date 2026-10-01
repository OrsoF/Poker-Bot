from dataclasses import replace
from types import SimpleNamespace

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
from src.models import ObservedState
from src.reader.game_state import parse_visible_state
from src.strategy.conservative import Recommendation, decide
from src.vision import dom_cards
from src.vision.cards import CardRead
from src.vision.reader import VisionState


def _observation(**changes) -> TableObservation:
    snapshot = TableObservation(
        hero_turn=True,
        state=ObservedState(
            hand="AKo", street="preflop", to_call=1.0, big_blind=1, can_check=False,
            hero_cards=("As", "Kh"),
            available_actions=frozenset({"FOLD", "CALL", "RAISE"}),
            raise_amount=2.5, pot_bb=2.5, hero_stack_bb=100.0,
            effective_stack_bb=100.0, active_players=2, hero_position="BTN",
        ),
        raw_text="",
        parsed_state=parse_visible_state(""),
        hero_reads=(CardRead("As", 1.0), CardRead("Kh", 1.0)),
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
    changed_amount = replace(snapshot, state=replace(snapshot.state, to_call=2.0))
    assert detector.observe(changed_amount) is None
    assert detector.observe(snapshot) is None
    assert detector.observe(snapshot) == snapshot

    audit_change = replace(
        snapshot,
        state=replace(snapshot.state, current_raise_to_bb=7, minimum_raise_to_bb=8),
        parsed_state=replace(snapshot.parsed_state, street="river"),
        hero_reads=(CardRead("As", 0.95), CardRead("Kh", 0.95)),
        hero_sources=("new-source", None),
        screenshot=b"different screenshot",
    )
    assert audit_change == snapshot
    assert hash(audit_change) == hash(snapshot)

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
        object(), decision, snapshot, lambda: changed_amount
    )
    assert control.clicks == 1

    state_changes = (
        {"street": "flop"}, {"available_actions": frozenset({"FOLD"})},
        {"raise_amount": 3.0}, {"pot_bb": 4.0}, {"hero_stack_bb": 90.0},
        {"effective_stack_bb": 80.0}, {"active_players": 3},
        {"hero_position": "CO"}, {"action_history": ("CHECK",)},
    )
    changed_snapshots = [
        replace(snapshot, state=replace(snapshot.state, **changes))
        for changes in state_changes
    ] + [
        replace(snapshot, hero_turn=False),
        replace(snapshot, hero_reads=(CardRead("Ah", 1.0), CardRead("Kh", 1.0))),
        replace(snapshot, board_reads=(CardRead("Qs", 1.0),)),
    ]
    for changed in changed_snapshots:
        assert changed != snapshot
        assert not _apply_action(object(), decision, snapshot, lambda: changed)
    assert control.clicks == 1

    unknown = replace(
        snapshot, state=replace(snapshot.state, hand=None, hero_cards=()),
        hero_reads=(CardRead(None, 0.0), CardRead("Kh", 1.0)),
    )
    assert unknown != replace(unknown, hero_reads=(CardRead(None, 0.0), CardRead("Qh", 1.0)))


def test_table_reader_merges_state_and_preserves_text_audit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    class Page(_CapturePage):
        def locator(self, selector):
            assert selector == "body"
            return self

        def inner_text(self, timeout):
            assert timeout == 2_000
            return (
                "ACTION 91 BB Nora 110 BB Wendy 173 BB Charles 19 BB "
                "Sakura 103 BB Maria 280 BB Pot: 9 BB Call: 7 BB Raise: 10.5 BB flop"
            )

    page = Page()
    empty = CardRead(None, 1.0, is_empty=True)
    known_hero = (CardRead("As", 1.0), CardRead("Kh", 1.0))
    monkeypatch.setattr(dom_cards, "hero_card_sources", lambda *_: (None, None))
    monkeypatch.setattr(dom_cards, "board_card_sources", lambda *_: (None,) * 5)
    monkeypatch.setattr(gambit_observation, "_is_hero_turn", lambda *_: True)
    monkeypatch.setattr(gambit_observation, "_read_six_max_position", lambda *_: "BTN")
    actions = frozenset({"FOLD", "CALL", "RAISE"})
    monkeypatch.setattr(gambit_observation, "available_actions", lambda _: actions)
    monkeypatch.setattr(gambit_observation, "live_call_amount", lambda _: 1.0)
    monkeypatch.setattr(gambit_observation, "live_raise_amount", lambda _: 2.5)
    monkeypatch.setattr(gambit_observation, "live_pot_amount", lambda *_: 4.5)

    expected = ObservedState(
        hand="AKo", street="preflop", to_call=1.0, big_blind=1, can_check=False,
        hero_stack_bb=91, hero_position="BTN", pot_bb=4.5,
        minimum_raise_to_bb=10.5, active_players=6, effective_stack_bb=19,
        hero_cards=("As", "Kh"), available_actions=actions, raise_amount=2.5,
    )
    cases = (
        (known_hero, (empty,) * 5, expected, "RAISE"),
        ((CardRead(None, 0.0), known_hero[1]), (empty,) * 5,
         replace(expected, hand=None, hero_cards=()), "FOLD"),
        (known_hero, (CardRead(None, 0.0), empty, empty, empty, empty),
         replace(expected, hand=None, hero_cards=(), street=None), "FOLD"),
    )
    for hero, board, expected_state, action in cases:
        vision = VisionState(hero=hero, board=board)
        reader = SimpleNamespace(read_screenshot=lambda _: vision, layout=None)
        observation = gambit_observation.read_table_observation(page, reader, None)
        state = observation.state
        assert state == expected_state
        assert decide(state).action == action
        # Unknown raw card slots must still participate in stability comparisons.
        assert observation.hero_cards == tuple(read.card for read in hero)
        assert observation.board_cards == tuple(read.card for read in board if not read.is_empty)

        records = []
        recorder = SimpleNamespace(write=lambda text, state, **kwargs: records.append(state))
        gambit._print_state(page, observation, "", recorder, False)
        text_state = parse_visible_state(page.inner_text(2_000), read_coaching_hand=False)
        assert records == [replace(text_state, hero_position="BTN")]
        assert "street=flop" in capsys.readouterr().out

    dom_reads = dict(zip(("hero-a", "hero-k", "board-q", "board-j", "board-t"), (
        *known_hero, CardRead("Qs", 1.0), CardRead("Jc", 1.0), CardRead("Tc", 1.0),
    )))
    monkeypatch.setattr(dom_cards, "hero_card_sources", lambda *_: ("hero-a", "hero-k"))
    monkeypatch.setattr(dom_cards, "board_card_sources", lambda *_: ("board-q", "board-j", "board-t", None, None))
    matcher = SimpleNamespace(read=dom_reads.__getitem__)
    captures = page.captures
    observation = gambit_observation.read_table_observation(page, reader, matcher)
    assert page.captures == captures
    assert observation.state == replace(expected, street="flop", board_cards=("Qs", "Jc", "Tc"))
    assert decide(observation.state).action == "FOLD"

    actions = frozenset({"FOLD", "CHECK", "RAISE"})
    monkeypatch.setattr(gambit_observation, "live_pot_amount", lambda *_: 0.0)
    observation = gambit_observation.read_table_observation(page, reader, matcher)
    assert observation.state == replace(
        expected, street="flop", board_cards=("Qs", "Jc", "Tc"),
        available_actions=actions, can_check=True, to_call=None, pot_bb=9,
    )
    assert decide(observation.state).action == "CHECK"

    observation = gambit_observation.read_table_observation(page, None, None)
    assert not observation.hero_turn
    assert observation.state == replace(
        expected, hand=None, hero_cards=(), hero_position=None, street="flop", pot_bb=9,
        available_actions=actions, can_check=True, to_call=None,
    )
