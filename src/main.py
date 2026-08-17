import argparse

from src.browser.gambit import inspect_table, observe_table
from src.strategy.conservative import ObservedState, decide


def run_dry_run() -> None:
    """Exercise the same safe strategy used by the live browser path."""
    decision = decide(
        ObservedState(
            hand=None,
            street="preflop",
            to_call=None,
            big_blind=None,
            can_check=False,
            available_actions=frozenset({"FOLD"}),
        )
    )
    print(f"DRY RUN: {decision.action} — {decision.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Observe a poker table safely.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("dry-run", help="Run the offline decision check.")

    def browser_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--interval", type=float, default=1.0, help="Seconds between observations.")
        command.add_argument("--url", default=None, help="Optional Gambit table URL to open after login.")
        return command

    browser_command("observe", "Open the browser and print table-state changes without screenshots or clicks.")
    browser_command("inspect", "Save visible card/control metadata and screenshots without clicking.")
    browser_command("train", "Record screenshots and ask for labels for unrecognized cards; never click.")
    browser_command(
        "assist",
        "Show card vision, hand strength, and conservative recommendations while you play manually.",
    )
    play = browser_command("play", "Use vision and conservative autoplay while recording observations.")
    play.add_argument(
        "--hand-strength",
        action="store_true",
        help="Print the best confirmed hand on the flop, turn, and river.",
    )
    args = parser.parse_args()

    if args.command in (None, "dry-run"):
        run_dry_run()
        return
    if args.command == "inspect":
        inspect_table(interval_seconds=args.interval, target_url=args.url)
        return

    observe_table(
        interval_seconds=args.interval,
        target_url=args.url,
        record=args.command in {"train", "assist", "play"},
        auto_play=args.command == "play",
        record_dom=False,
        vision=args.command in {"train", "assist", "play"},
        hand_strength=args.command == "assist" or (args.command == "play" and args.hand_strength),
    )


if __name__ == "__main__":
    main()
