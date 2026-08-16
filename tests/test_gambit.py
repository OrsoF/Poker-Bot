from src.browser.gambit import CALL_LABEL, FOLD_LABEL, GAMBIT_URL


def test_gambit_url_uses_https() -> None:
    assert GAMBIT_URL.startswith("https://")


def test_fold_pattern_rejects_non_fold_actions() -> None:
    assert FOLD_LABEL.fullmatch("Fold")
    assert FOLD_LABEL.search("Fold (F)")
    assert not FOLD_LABEL.fullmatch("Call")


def test_call_pattern_accepts_gambit_chip_labels() -> None:
    assert CALL_LABEL.fullmatch("Call: 1.0 BB")
    assert CALL_LABEL.fullmatch("Call: 0.5 BB")
    assert CALL_LABEL.fullmatch("Call: 2")
    assert not CALL_LABEL.fullmatch("Raise: 2.0 BB")
