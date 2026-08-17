"""Static six-max preflop ranges used by the conservative policy."""


def _hands(values: str) -> frozenset[str]:
    return frozenset(values.split())


PREFLOP_OPEN_RANGES = {
    "UTG": _hands("AA KK QQ JJ TT 99 88 77 AKs AQs AJs ATs AKo AQo KQs"),
    "HJ": _hands(
        "AA KK QQ JJ TT 99 88 77 66 AKs AQs AJs ATs AKo AQo AJo "
        "KQs KJs KQo QJs JTs"
    ),
    "CO": _hands(
        "AA KK QQ JJ TT 99 88 77 66 55 AKs AQs AJs ATs A9s A8s "
        "AKo AQo AJo KQs KJs KTs KQo QJs QTs JTs T9s 98s"
    ),
    "BTN": _hands(
        "AA KK QQ JJ TT 99 88 77 66 55 44 33 22 "
        "AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s "
        "AKo AQo AJo ATo A9o A8o KQs KJs KTs K9s K8s KQo KJo KTo "
        "QJs QTs Q9s QJo QTo JTs J9s JTo T9s 98s 87s 76s"
    ),
    "SB": _hands(
        "AA KK QQ JJ TT 99 88 77 66 55 44 33 22 "
        "AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s "
        "AKo AQo AJo ATo KQs KJs KTs K9s KQo KJo "
        "QJs QTs Q9s QJo JTs J9s T9s 98s 87s"
    ),
}

PREFLOP_CALL_OPEN = _hands("AA KK QQ JJ TT 99 AKs AQs AJs AKo AQo KQs")
PREFLOP_CALL_OPEN_IN_POSITION = PREFLOP_CALL_OPEN | _hands(
    "88 77 ATs KJs KQo QJs JTs"
)
PREFLOP_3BET_CONTINUE = _hands("AA KK QQ JJ AKs AQs AKo")
