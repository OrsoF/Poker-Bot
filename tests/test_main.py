import sys

import pytest

from src import main


@pytest.mark.parametrize("command", [[], ["dry-run"]])
def test_dry_run_is_the_default(monkeypatch: pytest.MonkeyPatch, command: list[str]) -> None:
    called = []
    monkeypatch.setattr(main, "run_dry_run", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", ["main", *command])

    main.main()

    assert called == [True]


@pytest.mark.parametrize(
    ("command", "record", "auto_play", "vision"),
    [
        ("observe", False, False, False),
        ("train", True, False, True),
        ("assist", True, False, True),
        ("play", True, True, True),
    ],
)
def test_browser_commands_select_their_fixed_mode(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    record: bool,
    auto_play: bool,
    vision: bool,
) -> None:
    received = {}
    monkeypatch.setattr(main, "observe_table", lambda **kwargs: received.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["main", command])

    main.main()

    assert received["record"] is record
    assert received["auto_play"] is auto_play
    assert received["vision"] is vision


def test_inspect_command_opens_the_read_only_inspector(monkeypatch: pytest.MonkeyPatch) -> None:
    received = {}
    monkeypatch.setattr(main, "inspect_table", lambda **kwargs: received.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["main", "inspect", "--interval", "2"])

    main.main()

    assert received == {"interval_seconds": 2.0, "target_url": None}
