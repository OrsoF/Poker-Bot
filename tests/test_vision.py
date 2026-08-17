from pathlib import Path

from PIL import Image

from src.vision.cards import CardRead, CardTemplateMatcher
from src.vision.hand_strength import evaluate_hand
from src.vision.stage import StableStageDetector, stage_from_board
from src.vision.training import normalize_card_label


def test_vision_cards_stage_and_hand_evaluation(tmp_path: Path) -> None:
    Image.new("RGB", (4, 4), "red").save(tmp_path / "Ah.png")
    Image.new("RGB", (4, 4), "red").save(tmp_path / "Ah--sample.png")
    matcher = CardTemplateMatcher(tmp_path)
    assert matcher.card_count == 1
    assert matcher.template_count == 2
    assert matcher.read(Image.new("RGB", (4, 4), "red")).card == "Ah"

    empty = CardRead(card=None, confidence=1.0, is_empty=True)
    flop = (
        CardRead(card="As", confidence=1.0, candidate="As"),
        CardRead(card="Kd", confidence=1.0, candidate="Kd"),
        CardRead(card="7c", confidence=1.0, candidate="7c"),
        empty,
        empty,
    )
    detector = StableStageDetector()
    assert stage_from_board(flop) == "flop"
    assert detector.observe(flop) is None
    assert detector.observe(flop) == "flop"

    hand = evaluate_hand(("Ah", "Kd"), ("Qs", "Jc", "Tc", "2h", "3d"))
    assert hand is not None
    assert hand.text == "Straight — aces high"
    assert normalize_card_label("10c") == "Tc"
    assert normalize_card_label("not a card") is None
