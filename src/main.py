import argparse

from src.browser.gambit import observe_table
from src.browser.mock_table import MockTable
from src.safety.limits import Limits
from src.strategy.rules import choose_action


def run_dry_run() -> None:
    table = MockTable()
    limits = Limits(max_hands=20, stop_loss=0)
    state = table.read_state()
    action = choose_action(state)

    if limits.allows(action):
        table.perform(action)


def main() -> None:
    parser = argparse.ArgumentParser(description="Observe a poker table safely.")
    parser.add_argument("--observe", action="store_true", help="Open the visible browser observer.")
    parser.add_argument(
        "--auto-fold",
        action="store_true",
        help="Explicitly allow clicking a visible, enabled Fold button.",
    )
    parser.add_argument(
        "--auto-play",
        action="store_true",
        help="Apply conservative Fold/Check/small-Call decisions at detected turns.",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Save visible state changes to data/observations/ for parser tuning.",
    )
    parser.add_argument(
        "--record-dom",
        action="store_true",
        help="Include visible control/card metadata in recorded observations.",
    )
    parser.add_argument(
        "--vision",
        action="store_true",
        help="Read configured card regions from a screenshot using local templates.",
    )
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between observations.")
    parser.add_argument("--url", default=None, help="Optional game/table URL to open after login.")
    parser.add_argument(
        "--strategy",
        choices=("fold-only", "conservative"),
        default="fold-only",
        help="fold-only clicks Fold; conservative currently reports validated recommendations.",
    )
    args = parser.parse_args()

    if args.auto_fold and not args.observe:
        parser.error("--auto-fold requires --observe")
    if args.auto_fold and args.strategy != "fold-only":
        parser.error("--auto-fold is only available with --strategy fold-only")
    if args.auto_play and args.strategy != "conservative":
        parser.error("--auto-play requires --strategy conservative")
    if args.record_dom and not args.record:
        parser.error("--record-dom requires --record")

    if args.observe:
        observe_table(
            auto_fold=args.auto_fold,
            interval_seconds=args.interval,
            target_url=args.url,
            strategy=args.strategy,
            record=args.record,
            auto_play=args.auto_play,
            record_dom=args.record_dom,
            vision=args.vision,
        )
    else:
        run_dry_run()


if __name__ == "__main__":
    main()
