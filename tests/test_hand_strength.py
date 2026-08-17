from src.strategy.hand_strength import analyze_draws, evaluate_hand, flush_draw_equity


def test_reports_pair_from_flop() -> None:
    hand = evaluate_hand(("Ah", "Kd"), ("As", "7c", "2h"))
    assert hand is not None
    assert hand.text == "Pair — aces"


def test_uses_best_five_cards_on_river() -> None:
    hand = evaluate_hand(("Ah", "Kd"), ("Qs", "Jc", "Tc", "2h", "3d"))
    assert hand is not None
    assert hand.text == "Straight — aces high"


def test_rejects_duplicate_or_unknown_cards() -> None:
    assert evaluate_hand(("Ah", "Ah"), ("Qs", "Jc", "Tc")) is None
    assert evaluate_hand(("Ah", None), ("Qs", "Jc", "Tc")) is None


def test_detects_a_confirmed_nut_flush_draw() -> None:
    draw = analyze_draws(("Ah", "Kh"), ("2h", "7h", "Tc"))
    assert draw is not None
    assert draw.has_flush_draw
    assert draw.nut_flush_draw


def test_does_not_guess_a_draw_when_a_card_is_unread() -> None:
    assert analyze_draws(("Ah", "Kd"), ("2h", "7h", None)) is None


def test_flush_draw_equity_is_lower_on_the_turn_and_for_non_nut_draws() -> None:
    assert flush_draw_equity("flop", True) == 0.35
    assert flush_draw_equity("turn", True) == 0.196
    assert flush_draw_equity("flop", False) < flush_draw_equity("flop", True)
