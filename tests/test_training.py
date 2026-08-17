from src.vision.training import CONFIRMATION_CONFIDENCE, normalize_card_label


def test_normalizes_interactive_card_labels() -> None:
    assert normalize_card_label("10c") == "Tc"
    assert normalize_card_label(" as ") == "As"
    assert normalize_card_label("1h") is None
    assert normalize_card_label("ten clubs") is None


def test_confirmation_threshold_is_more_strict_than_match_threshold() -> None:
    assert CONFIRMATION_CONFIDENCE > 0.92
