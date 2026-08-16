from src.vision.cards import CardRead
from src.vision.stage import StableStageDetector, stage_from_board


def _empty() -> CardRead:
    return CardRead(card=None, confidence=1.0, is_empty=True)


def _card(name: str) -> CardRead:
    return CardRead(card=name, confidence=1.0, candidate=name)


def test_stage_is_derived_from_confirmed_board_card_count() -> None:
    assert stage_from_board((_empty(),) * 5) == "preflop"
    assert stage_from_board((_card("As"), _card("Kd"), _card("7c"), _empty(), _empty())) == "flop"
    assert stage_from_board((_card("As"), _card("Kd"), _card("7c"), _card("2h"), _empty())) == "turn"
    assert stage_from_board((_card("As"), _card("Kd"), _card("7c"), _card("2h"), _card("Tc"))) == "river"


def test_stage_rejects_unstable_or_backward_observations() -> None:
    detector = StableStageDetector()
    preflop = (_empty(),) * 5
    flop = (_card("As"), _card("Kd"), _card("7c"), _empty(), _empty())
    assert detector.observe(preflop) is None
    assert detector.observe(preflop) == "preflop"
    assert detector.observe(flop) is None
    assert detector.observe(flop) == "flop"
    assert detector.observe(preflop) is None
    assert detector.observe(preflop) is None
