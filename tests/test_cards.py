from pathlib import Path

from PIL import Image

from src.vision.cards import CardTemplateMatcher


def test_template_matcher_accepts_multiple_samples_per_card(tmp_path: Path) -> None:
    Image.new("RGB", (4, 4), "red").save(tmp_path / "Ah.png")
    Image.new("RGB", (4, 4), "red").save(tmp_path / "Ah--second-sample.png")
    Image.new("RGB", (4, 4), "blue").save(tmp_path / "2s.png")

    matcher = CardTemplateMatcher(tmp_path)

    assert matcher.card_count == 2
    assert matcher.template_count == 3
    assert matcher.read(Image.new("RGB", (4, 4), "red")).card == "Ah"
