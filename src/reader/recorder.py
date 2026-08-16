"""Append visible table observations to a local JSONL file for parser tuning."""

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from src.strategy.conservative import ObservedState


class ObservationRecorder:
    def __init__(self) -> None:
        directory = Path("data/observations")
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = directory / f"gambit-{stamp}.jsonl"

    def write(
        self,
        visible_text: str,
        state: ObservedState,
        hero_turn: bool,
        dom_map: dict[str, object] | None = None,
    ) -> None:
        record = {
            "recorded_at": datetime.now().astimezone().isoformat(),
            "visible_text": visible_text,
            "parsed": asdict(state),
            "hero_turn": hero_turn,
        }
        if dom_map is not None:
            record["visible_dom"] = dom_map
        with self.path.open("a", encoding="utf-8") as output:
            json.dump(record, output, ensure_ascii=False)
            output.write("\n")
