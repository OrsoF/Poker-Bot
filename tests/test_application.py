import json
import sys
from pathlib import Path

import pytest

from src import main
from src.reader.recorder import ObservationRecorder
from src.strategy.conservative import ObservedState
from src.strategy.models import TableState
from src.strategy.rules import choose_action


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
        ),
        hero_turn=True,
    )
    record = json.loads(recorder.path.read_text(encoding="utf-8"))
    assert record["parsed"]["available_actions"] == ["CALL", "FOLD", "RAISE"]
    assert choose_action(TableState(to_call=0, minimum_raise=2, stack=100)).kind == "check"
