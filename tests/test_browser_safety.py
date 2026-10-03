from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.browser import gambit, gambit_controls, gambit_observation
from src.browser.gambit import _apply_action
from src.browser.gambit_observation import (
    GambitTableReader,
    HeroTurnScreenshotCache,
    StableObservationDetector,
    TableObservation,
    _needs_screenshot,
)
from src.browser.gambit_positions import SIX_MAX_POSITIONS, read_seats, seats_from_geometry
from src.models import ObservedState, SeatObservation
from src.reader.game_state import parse_visible_state
from src.strategy.conservative import Recommendation, decide
from src.strategy.allin import decide as decide_allin
from src.vision import dom_cards
from src.vision.cards import CardRead
from src.vision.reader import VisionState
from src.vision.layout import load_layout


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
        {"all_in_amount": 2.5},
        {"effective_stack_bb": 80.0}, {"active_players": 3},
        {"hero_position": "CO"}, {"action_history": ("CHECK",)},
        {"seats": (SeatObservation(0, "Jade", 471, "HJ"),)},
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
    seats = (
        SeatObservation(0, "Nora", 110, "UTG"), SeatObservation(1, "Wendy", 173, "HJ"),
        SeatObservation(2, "Charles", 19, "CO"),
        SeatObservation(3, None, 91, "BTN", is_hero=True, is_dealer=True),
        SeatObservation(4, "Sakura", 103, "SB"), SeatObservation(5, "Maria", 280, "BB"),
    )
    monkeypatch.setattr(gambit_observation, "read_seats", lambda *_: seats)
    actions = frozenset({"FOLD", "CALL", "RAISE"})
    monkeypatch.setattr(gambit_observation, "available_actions", lambda _: actions)
    monkeypatch.setattr(gambit_observation, "live_call_amount", lambda _: 1.0)
    monkeypatch.setattr(gambit_observation, "live_raise_amount", lambda _: 2.5)
    monkeypatch.setattr(gambit_observation, "live_all_in_amount", lambda _: None)
    monkeypatch.setattr(gambit_observation, "live_pot_amount", lambda *_: 4.5)

    expected = ObservedState(
        hand="AKo", street="preflop", to_call=1.0, big_blind=1, can_check=False,
        hero_stack_bb=91, hero_position="BTN", pot_bb=4.5,
        minimum_raise_to_bb=10.5, active_players=6, effective_stack_bb=19,
        hero_cards=("As", "Kh"), available_actions=actions, raise_amount=2.5,
        seats=seats,
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
        gambit._print_state(page, observation, None, recorder, False)
        text_state = parse_visible_state(page.inner_text(2_000), read_coaching_hand=False)
        assert records == [replace(text_state, hero_position="BTN", seats=seats)]
        assert f"street={state.street or '?'}" in capsys.readouterr().out

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
        available_actions=actions, can_check=True, to_call=None, seats=(),
    )

    # Preserve the selected submission label in the merged state so the
    # pre-click comparison catches it disappearing with an unchanged amount.
    monkeypatch.setattr(gambit_observation, "live_raise_amount", lambda _: 166.0)
    monkeypatch.setattr(gambit_observation, "live_all_in_amount", lambda _: 166.0)
    for vision_reader in (reader, None):
        selected = gambit_observation.read_table_observation(page, vision_reader, matcher)
        assert selected.state.raise_amount == selected.state.all_in_amount == 166.0

    # Positions and stacks remain observable on an opponent's turn. Moving
    # ACTION must not change the hero seat or fabricate a position without D.
    monkeypatch.setattr(gambit_observation, "_is_hero_turn", lambda *_: False)
    off_turn = gambit_observation.read_table_observation(page, reader, matcher)
    assert not off_turn.hero_turn
    assert off_turn.state.hero_position == "BTN"
    assert off_turn.state.seats == seats
    seats = tuple(replace(seat, position=None, is_dealer=False) for seat in seats)
    no_dealer = gambit_observation.read_table_observation(page, reader, matcher)
    assert no_dealer.state.hero_position is None
    assert no_dealer.state.seats == seats


def test_six_max_seats_stacks_and_dealer_recording(capsys: pytest.CaptureFixture) -> None:
    # Rendered points from the supplied six-max layout; Jimmy remains seated
    # after folding. ACTION is deliberately absent from the position input.
    points = ((550, 186), (919, 259), (919, 480), (550, 540), (181, 480), (181, 259))
    names = ("Jade", "Pierre", "Wendy", None, "Sakura", "Jimmy")
    stacks = (471, 412, 630, 163, 188, 435)
    geometry = dict(
        bounds=(156, 100, 780, 480), hero=points[3], heroStack=163,
        players=[dict(name=name, stack=stack, point=point)
                 for name, stack, point in zip(names, stacks, points) if name],
        buttons=[(847, 422)],
    )
    seats = seats_from_geometry(geometry)
    assert [seat.position for seat in seats] == ["HJ", "CO", "BTN", "SB", "BB", "UTG"]
    assert [seat.stack_bb for seat in seats] == list(stacks)
    assert [seat.name for seat in seats] == list(names)
    assert seats[3].is_hero and seats[2].is_dealer
    for dealer in range(6):
        rotated = seats_from_geometry(dict(geometry, buttons=[points[dealer]]))
        assert [seat.position for seat in rotated] == [SIX_MAX_POSITIONS[(index - dealer) % 6] for index in range(6)]
    for buttons in ([], [points[0], points[1]], [(550, 340)], [(734.5, 222.5)]):
        unknown = seats_from_geometry(dict(geometry, buttons=buttons))
        assert len(unknown) == 6
        assert all(seat.position is None and not seat.is_dealer for seat in unknown)
    assert not seats_from_geometry(dict(geometry, players=geometry["players"][:-1]))
    assert not seats_from_geometry(dict(geometry, players=geometry["players"] * 2))
    assert not seats_from_geometry(None)
    missing_stack = seats_from_geometry(dict(geometry, heroStack=None))
    assert missing_stack[3].stack_bb is None
    named_hero = seats_from_geometry(dict(geometry, players=geometry["players"] + [
        dict(name="Orso", stack=163, point=points[3]),
    ]))
    assert named_hero[3].name == "Orso" and named_hero[3].is_hero

    layout = SimpleNamespace(hero=(SimpleNamespace(x=.45, y=.68, width=.05, height=.12),) * 2)
    class Page:
        def locator(self, selector):
            assert selector == "body"
            return self

        def evaluate(self, script, regions):
            assert "dealer-button" in script
            assert regions == [[.45, .68, .05, .12]] * 2
            return geometry

    assert read_seats(Page(), layout) == seats
    records = []
    recorder = SimpleNamespace(write=lambda text, state, **kwargs: records.append(state))
    observation = _observation(hero_turn=False)
    observation = replace(observation, state=replace(observation.state, seats=seats, hero_position="SB"))
    previous = gambit._print_state(Page(), observation, None, recorder, False)
    assert records[-1].seats == seats
    output = capsys.readouterr().out
    assert "Wendy BTN 630 BB" in output
    assert "stack=163 BB" in output
    assert gambit._print_state(Page(), observation, previous, recorder, False) == previous
    assert len(records) == 1
    # Text animations/coaching changes retain their audit record without
    # repeating an unchanged terminal summary.
    previous = gambit._print_state(Page(), replace(observation, raw_text="changed animation"), previous, recorder, False)
    assert not capsys.readouterr().out
    assert len(records) == 2
    moved = seats_from_geometry(dict(geometry, buttons=[points[0]]))
    observation = replace(observation, state=replace(observation.state, seats=moved, hero_position="UTG"))
    previous = gambit._print_state(Page(), observation, previous, recorder, False)
    assert len(records) == 3 and records[-1].seats == moved
    capsys.readouterr()
    resized = tuple(replace(seat, stack_bb=500) if seat.name == "Wendy" else seat for seat in moved)
    assert replace(observation, state=replace(observation.state, seats=resized)) != observation
    gambit._print_state(Page(), replace(observation, state=replace(observation.state, seats=resized)), previous, recorder, False)
    output = capsys.readouterr().out
    assert "SEATS:" in output and "STATE:" not in output

    # Vision mode records every changed observation, but displays only stable
    # decisions. Stack changes alone do not repeat the whole seating ring.
    previous = gambit._print_state(Page(), observation, None, recorder, False, quiet=True)
    assert not capsys.readouterr().out
    previous = gambit._print_state(
        Page(), replace(observation, raw_text="opponent animation"), previous,
        recorder, False, quiet=True,
    )
    assert not capsys.readouterr().out
    assert records[-1].seats == moved
    decision = Recommendation("FOLD", "All-in requires confirmed preflop cards in the selected range; fail-safe fold")
    observation = replace(
        observation,
        state=replace(observation.state, hand="A3o", hero_cards=("Ad", "3h")),
        hero_reads=(CardRead("Ad", 1.0), CardRead("3h", 1.0)),
        board_reads=(CardRead(None, 1.0, is_empty=True),) * 5,
    )
    seat_key = gambit._print_decision(observation, decision, 3, "allin", False, None)
    output = capsys.readouterr().out
    assert "MAIN 3 · PRÉFLOP" in output
    assert "CARTES: Ad 3h" in output and "100%" not in output
    assert "BOARD:" not in output
    assert "A3o hors range allin" in output
    assert "SIÈGES:" in output and "STATE:" not in output and "TURN:" not in output
    resized_observation = replace(observation, state=replace(observation.state, seats=resized))
    gambit._print_decision(resized_observation, decision, 3, "allin", False, seat_key)
    assert "SIÈGES:" not in capsys.readouterr().out
    incomplete = replace(observation, state=replace(
        observation.state, hero_position=None, hero_stack_bb=None,
        effective_stack_bb=None, active_players=None, seats=(),
    ))
    gambit._print_decision(incomplete, decision, 4, "allin", False, seat_key)
    output = capsys.readouterr().out
    assert "LECTURE INCOMPLÈTE: position, tapis, effectif, joueurs actifs" in output
    assert "SIÈGES:" not in output and "SEATS: unavailable" not in output
    assert gambit._format_card_reads((CardRead(None, .75, candidate="Ad"),)) == "Ad? (75%)"


def test_captured_gambit_dom_positions_stacks_and_hero_turn(tmp_path: Path) -> None:
    from playwright.sync_api import Error, sync_playwright

    layout = load_layout(Path("config/vision.example.json"))
    assert layout is not None
    empty = CardRead(None, 1.0, is_empty=True)
    vision = SimpleNamespace(layout=layout, read_screenshot=lambda _: VisionState(
        hero=(empty, empty), board=(empty,) * 5,
    ))
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip("Install Playwright Chromium to run the captured DOM scenario")
            raise
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.route("**/*", lambda route: route.abort())
            page.set_content((Path(__file__).parent / "fixtures/gambit_six_max.html").read_text(encoding="utf-8"))
            matcher = dom_cards.DomCardMatcher(tmp_path / "cards.json")
            matcher.add("8c", page.locator("#card-a").get_attribute("src"))
            matcher.add("2h", page.locator("#card-b").get_attribute("src"))
            reader = GambitTableReader(page, vision, matcher)
            initial = reader.read()
            assert initial.hero_turn
            assert initial.state.hero_cards == ("8c", "2h")
            assert initial.state.hero_position == "SB"
            assert initial.state.hero_stack_bb == 208
            assert initial.state.active_players == 4
            assert initial.state.effective_stack_bb == 137
            assert initial.state.current_raise_to_bb == 36
            assert (initial.state.to_call, initial.state.raise_amount) == (35, 108)
            assert [seat.name for seat in initial.state.seats] == ["Sven", "Charles", "Pierre", None, "Nora", "Jimmy"]
            assert [seat.stack_bb for seat in initial.state.seats] == [213, 548, 137, 208, 172, 1073]
            assert [seat.position for seat in initial.state.seats] == ["HJ", "CO", "BTN", "SB", "BB", "UTG"]
            assert {seat.name for seat in initial.state.seats if seat.folded} == {"Jimmy", "Sven"}
            detector = StableObservationDetector()
            assert detector.observe(initial) is None
            assert detector.observe(reader.read()) == initial

            # Nested wrappers must not count a badge/name/stack pair again.
            # The rendered labels and geometry stay unchanged after wrapping.
            page.locator(".seat").evaluate_all("""elements => elements.forEach(element => {
              const outer = document.createElement('div');
              const inner = document.createElement('div');
              while (element.firstChild) inner.append(element.firstChild);
              outer.append(inner);
              element.append(outer);
            })""")
            nested = reader.read()
            assert nested.state.seats == initial.state.seats
            assert nested.state.hero_position == "SB"
            assert nested.state.hero_stack_bb == 208
            assert nested.state.active_players == 4
            assert nested.state.effective_stack_bb == 137
            assert detector.observe(nested) == initial

            # The CSS-background D, and every stack, survive an opponent turn.
            page.locator("#hero-badge").evaluate("e => {e.style.left='1049px';e.style.top='453px';}")
            off_turn = reader.read()
            assert not off_turn.hero_turn
            assert off_turn.state.seats == initial.state.seats
            assert off_turn.state.hero_stack_bb == 208
            assert reader.screenshot_cache.screenshot is None

            page.locator("#hero-badge").evaluate("e => {e.style.left='678px';e.style.top='587px';}")
            # A hidden old ACTION badge must not validate or invalidate a turn.
            page.locator("body").evaluate("body => {const old=document.createElement('div');old.id='old';old.style='opacity:0;position:absolute;left:678px;top:587px';old.innerText='ACTION';body.append(old);}")
            assert reader.read().hero_turn
            page.locator("#old").evaluate("e => e.style.opacity='1'")
            assert not reader.read().hero_turn
            page.locator("#old").evaluate("e => e.style.opacity='0'")
            page.locator("#dealer").evaluate("e => e.style.opacity='0'")
            assert all(seat.position is None for seat in reader.read().state.seats)
            page.locator("#dealer").evaluate("e => e.style.opacity='1'")
            page.locator("#hero-badge").evaluate("e => e.innerText='FOLD'")
            folded = reader.read()
            assert not folded.hero_turn
            assert next(seat for seat in folded.state.seats if seat.is_hero).folded
            assert folded.state.active_players == 3
            page.locator("#hero-stack").evaluate("e => e.remove()")
            missing_stack = reader.read()
            assert missing_stack.state.hero_stack_bb is None
            assert missing_stack.state.effective_stack_bb is None
            assert missing_stack.state.hero_position == "SB"
            page.locator("#table > div").evaluate("e => e.style.backgroundImage='none'")
            assert not reader.read().state.seats
        finally:
            browser.close()


def test_allin_sizing_and_submit_require_unchanged_table(monkeypatch: pytest.MonkeyPatch) -> None:
    class Control(_Control):
        def __init__(self, label):
            super().__init__()
            self.label = label
            self.on_click = lambda: None

        def click(self, timeout):
            super().click(timeout)
            self.on_click()

        def is_visible(self):
            return True

        def inner_text(self):
            return self.label

    controls = [Control(label) for label in ("All-In", "Fold", "Call: 1", "Raise: 2.5")]
    def get_by_text(label, exact):
        assert exact
        return SimpleNamespace(all=lambda: [
            control for control in controls
            if (label == control.label if isinstance(label, str) else label.fullmatch(control.label))
        ])

    page = SimpleNamespace(get_by_text=get_by_text)
    assert gambit_controls.available_actions(page) == frozenset({"ALL_IN", "FOLD", "CALL", "RAISE"})
    assert gambit_controls.find_action_control(page, "ALL_IN") is controls[0]
    raise_control = controls.pop()
    assert "ALL_IN" not in gambit_controls.available_actions(page)
    controls.append(raise_control)

    snapshot = _observation()
    snapshot = replace(snapshot, state=replace(
        snapshot.state, hero_position=None, hero_stack_bb=None,
        action_history=("RAISE 10 BB",), to_call=10,
        available_actions=snapshot.state.available_actions | {"ALL_IN"},
    ))
    prepared = replace(snapshot, state=replace(snapshot.state, raise_amount=100))
    decision = decide_allin(snapshot.state)
    assert decision.action == "ALL_IN"
    detector = StableObservationDetector()
    assert detector.observe(snapshot) is None
    assert detector.observe(snapshot) == snapshot
    monkeypatch.setattr(gambit, "sleep", lambda _: None)
    monkeypatch.setattr(gambit, "_find_action_control", gambit_controls.find_action_control)

    scenarios = (
        ([snapshot, prepared, prepared], True, 1, 1),
        ([replace(snapshot, hero_turn=False)], False, 0, 0),
        ([replace(snapshot, state=replace(snapshot.state, raise_amount=3))], False, 0, 0),
        ([snapshot, replace(prepared, hero_turn=False)], False, 1, 0),
        ([snapshot, replace(prepared, state=replace(prepared.state, street="flop"))], False, 1, 0),
        ([snapshot, replace(prepared, hero_reads=(CardRead("Qs", 1.0), CardRead("Kh", 1.0)))], False, 1, 0),
        ([snapshot, replace(prepared, state=replace(prepared.state, raise_amount=None))], False, 1, 0),
        ([snapshot, replace(prepared, state=replace(prepared.state, raise_amount=1))], False, 1, 0),
        ([snapshot, snapshot], False, 1, 0),
        ([snapshot, prepared, replace(prepared, state=replace(prepared.state, raise_amount=101))], False, 1, 0),
        ([snapshot, prepared, replace(prepared, state=replace(prepared.state, available_actions=frozenset({"FOLD"})))], False, 1, 0),
    )
    for observations, applied, sizing_clicks, raise_clicks in scenarios:
        for control in controls:
            control.clicks = 0
        reads = iter(observations)
        assert _apply_action(page, decision, snapshot, lambda: next(reads)) is applied
        assert controls[0].clicks == sizing_clicks
        assert raise_control.clicks == raise_clicks
        assert controls[1].clicks == controls[2].clicks == 0

    # Recorded Gambit panel: Raise: 5 becomes All-In: 166 after sizing,
    # while Call: 2 stays the ordinary call. No visible hero stack is needed.
    controls[2].label = "Call: 2"
    snapshot = replace(snapshot, state=replace(
        snapshot.state, to_call=2, raise_amount=5,
    ))

    def read_live_panel():
        return replace(snapshot, state=replace(
            snapshot.state,
            available_actions=gambit_controls.available_actions(page),
            to_call=gambit_controls.live_call_amount(page),
            raise_amount=gambit_controls.live_raise_amount(page),
            all_in_amount=gambit_controls.live_all_in_amount(page),
        ))

    def select_allin():
        raise_control.label = "All-In: 166"

    controls[0].on_click = select_allin
    for initial_label in ("Raise: 5", "All-In: 166"):
        raise_control.label = initial_label
        for control in controls:
            control.clicks = 0
        initial = read_live_panel()
        assert decide_allin(initial.state).action == "ALL_IN"
        assert _apply_action(page, decide_allin(initial.state), initial, read_live_panel)
        assert controls[0].clicks == raise_control.clicks == 1
        assert controls[1].clicks == controls[2].clicks == 0

    # A missing/malformed submission label cancels sizing. Reproduce the
    # next two loop reads as well: they must never turn that cancellation
    # into a Fold on the same confirmed premium hand.
    for missing_label in ("All-In: ?", "All-In: 0"):
        raise_control.label = "Raise: 5"
        controls[0].on_click = lambda: setattr(raise_control, "label", missing_label)
        for control in controls:
            control.clicks = 0
        initial = read_live_panel()
        assert not _apply_action(page, decide_allin(initial.state), initial, read_live_panel)
        detector.reset()
        assert detector.observe(read_live_panel()) is None
        stable = detector.observe(read_live_panel())
        assert stable is not None
        assert decide_allin(stable.state).action == "NO_ACTION"
        assert controls[0].clicks == 1
        assert controls[1].clicks == controls[2].clicks == raise_control.clicks == 0

        select_allin()
        controls[0].on_click = select_allin
        recovered = read_live_panel()
        assert _apply_action(page, decide_allin(recovered.state), recovered, read_live_panel)
        assert raise_control.clicks == 1
        assert controls[1].clicks == controls[2].clicks == 0

    # If the All-In label changes back to Raise before submitting, cancel
    # even when the numeric amount stays the same.
    raise_control.label = "Raise: 5"
    controls[0].on_click = select_allin
    for control in controls:
        control.clicks = 0
    initial = read_live_panel()
    reads = 0

    def changed_before_submit():
        nonlocal reads
        reads += 1
        if reads == 3:
            raise_control.label = "Raise: 166"
        return read_live_panel()

    assert not _apply_action(page, decide_allin(initial.state), initial, changed_before_submit)
    assert controls[0].clicks == 1
    assert controls[1].clicks == controls[2].clicks == raise_control.clicks == 0
