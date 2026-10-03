import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import main
from src.browser import gambit_inspector
from src.reader.recorder import ObservationRecorder
from src.models import ObservedState, SeatObservation


def test_cli_recorder_and_offline_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dry_run_calls = []
    monkeypatch.setattr(main, "run_dry_run", lambda: dry_run_calls.append(True))
    monkeypatch.setattr(sys, "argv", ["main"])
    main.main()
    assert dry_run_calls == [True]

    play_args = {}
    monkeypatch.setattr(main, "observe_table", lambda **kwargs: play_args.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["main", "play", "--hand-strength"])
    main.main()
    assert play_args["auto_play"] and play_args["vision"] and play_args["hand_strength"]

    default_args = {
        "interval_seconds": 1.0,
        "target_url": None,
        "record_dom": False,
        "strategy": "conservative",
    }
    scenarios = (
        (["assist"], {"record": True, "auto_play": False, "vision": True, "hand_strength": True}),
        (["play"], {"record": True, "auto_play": True, "vision": True, "hand_strength": False}),
        (["play", "allin"], {
            "record": True, "auto_play": True, "vision": True, "hand_strength": False,
            "strategy": "allin",
        }),
        (["assist", "allin"], {
            "record": True, "auto_play": False, "vision": True, "hand_strength": True,
            "strategy": "allin",
        }),
        (["assist", "--no-vision", "--interval", "2", "--url", "https://gambit.com/table"], {
            "record": False, "auto_play": False, "vision": False, "hand_strength": False,
            "interval_seconds": 2.0, "target_url": "https://gambit.com/table",
        }),
    )
    for arguments, expected in scenarios:
        play_args.clear()
        monkeypatch.setattr(sys, "argv", ["main", *arguments])
        main.main()
        assert play_args == default_args | expected

    inspect_args = {}
    monkeypatch.setattr(main, "inspect_table", lambda **kwargs: inspect_args.update(kwargs))
    play_args.clear()
    monkeypatch.setattr(sys, "argv", ["main", "inspect", "--interval", "3"])
    main.main()
    assert inspect_args == {"interval_seconds": 3.0, "target_url": None}
    assert not play_args

    for arguments in (["observe"], ["train"], ["dry-run"], ["play", "--no-vision"], ["play", "unknown"]):
        monkeypatch.setattr(sys, "argv", ["main", *arguments])
        with pytest.raises(SystemExit) as error:
            main.main()
        assert error.value.code == 2
        assert not play_args
    assert dry_run_calls == [True]

    recorder = ObservationRecorder()
    recorder.path = tmp_path / "observation.jsonl"
    recorder.write(
        "visible table",
        ObservedState(
            hand="AKs",
            street="preflop",
            to_call=1,
            big_blind=1,
            can_check=False,
            available_actions=frozenset({"RAISE", "FOLD", "CALL"}),
            seats=(SeatObservation(0, "Jade", 471, "HJ"),),
        ),
        hero_turn=True,
        observed_state=ObservedState(
            hand="AKs", street="preflop", to_call=1, big_blind=1, can_check=False,
            hero_position="SB", hero_stack_bb=163,
        ),
        decision={"action": "FOLD", "reason": "Full policy explanation", "amount": None},
        hand_number=3,
    )
    record = json.loads(recorder.path.read_text(encoding="utf-8"))
    assert record["parsed"]["available_actions"] == ["CALL", "FOLD", "RAISE"]
    assert record["observed"]["hero_position"] == "SB"
    assert record["observed"]["hero_stack_bb"] == 163
    assert record["decision"]["reason"] == "Full policy explanation"
    assert record["hand_number"] == 3
    assert record["parsed"]["seats"][0] == {
        "seat_index": 0, "name": "Jade", "stack_bb": 471, "position": "HJ",
        "is_hero": False, "is_dealer": False, "folded": False,
    }


def test_inspector_opens_bots_once_and_reports_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    from playwright.sync_api import Error

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gambit_inspector, "PROFILE_DIRECTORY", Path("profile"))
    for target_url, failures, closed in ((None, 0, False), ("https://gambit.com/table", 0, False),
                                         (None, 3, False), (None, 1, True)):
        events = []
        polls = 0
        lookups = 0
        sleeps = 0

        class Page:
            url = target_url or "https://gambit.com/"

            def goto(self, url, wait_until):
                assert wait_until == "domcontentloaded"
                events.append(("goto", url))

            def locator(self, selector):
                assert selector == "body"
                return self

            def inner_text(self, timeout):
                assert timeout == 2_000
                return "visible table"

            def screenshot(self, path):
                events.append(("screenshot", path))
                Path(path).write_bytes(b"fixture")

            def is_closed(self):
                return closed

        page = Page()
        context = SimpleNamespace(pages=[page], close=lambda: events.append(("close",)))

        @contextmanager
        def sync_playwright():
            yield SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: context,
            ))

        def lookup(candidate_page, label):
            nonlocal lookups
            assert candidate_page is page and label == "Play Bots"
            lookups += 1
            # First poll waits for manual login; later polls expose the button.
            if lookups == 1:
                return None
            return SimpleNamespace(click=lambda timeout: events.append(("click", label, timeout)))

        def dom_map(candidate_page):
            nonlocal polls
            assert candidate_page is page
            polls += 1
            if polls <= failures:
                raise Error("fixture capture failed")
            return {"controls": []}

        def sleep(seconds):
            nonlocal sleeps
            assert seconds == 1
            sleeps += 1
            if sleeps >= failures + 3:
                raise KeyboardInterrupt

        monkeypatch.setattr("playwright.sync_api.sync_playwright", sync_playwright)
        monkeypatch.setattr(gambit_inspector, "visible_text_control", lookup)
        monkeypatch.setattr(gambit_inspector, "visible_dom_map", dom_map)
        monkeypatch.setattr(gambit_inspector, "sleep", sleep)
        gambit_inspector.inspect_table(1, target_url)
        output = capsys.readouterr().out
        clicks = [event for event in events if event[0] == "click"]
        assert clicks == ([] if target_url or closed else [("click", "Play Bots", 2_000)])
        assert lookups == (0 if target_url else 1 if closed else 2)
        assert events[-1] == ("close",)
        if closed:
            assert "browser page closed" in output
        elif failures:
            assert output.count("WAIT: fixture capture failed") == 1
        if not closed:
            assert any(event[0] == "screenshot" for event in events)


def test_inspector_extracts_rendered_dom_and_screenshot(tmp_path: Path) -> None:
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip("Install Playwright Chromium to run the rendered DOM scenario")
            raise
        try:
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.set_content('''
                <div class="poker-table" style="width:600px;height:300px">
                  <button data-testid="fold" data-action="fold">Fold</button>
                  <button disabled>Call: 10</button>
                  <div role="button" aria-label="raise">Raise: 25</div>
                  <input type="button" value="Play Bots">
                  <button style="display:none">Hidden</button>
                  <svg class="card" width="40" height="60"><rect width="40" height="60"/></svg>
                </div>
            ''')
            dom = gambit_inspector.visible_dom_map(page)
            controls = {control["text"]: control for control in dom["controls"]}
            assert set(controls) == {"Fold", "Call: 10", "Raise: 25", "Play Bots"}
            assert controls["Fold"]["testId"] == "fold"
            assert controls["Fold"]["data"]["data-action"] == "fold"
            assert controls["Call: 10"]["disabled"]
            assert controls["Raise: 25"]["ariaLabel"] == "raise"
            assert all(control["rect"]["width"] > 0 and control["rect"]["height"] > 0
                       for control in controls.values())
            assert {candidate["text"] for candidate in dom["action_candidates"]} >= {"Fold", "Call: 10", "Raise: 25"}
            assert any(candidate["tag"] == "svg" for candidate in dom["card_candidates"])
            assert any(candidate["className"] == "poker-table" for candidate in dom["table_candidates"])
            # The inspector must be able to persist both artifacts from this DOM.
            json.dumps(dom)
            screenshot = tmp_path / "inspection.png"
            page.screenshot(path=str(screenshot))
            assert screenshot.read_bytes().startswith(b"\x89PNG")
        finally:
            browser.close()
