import argparse

from src.browser.gambit import inspect_table, observe_table
from src.models import ObservedState
from src.strategy.conservative import decide


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
    parser = argparse.ArgumentParser(
        description="Assist at a poker table. Without a command, run the offline decision check."
    )
    commands = parser.add_subparsers(dest="command")

    def browser_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--interval", type=float, default=1.0, help="Seconds between observations.")
        command.add_argument("--url", default=None, help="Optional Gambit table URL to open after login.")
        return command

    assist = browser_command(
        "assist",
        "Read cards, learn unknown cards, and show safe recommendations without clicking.",
    )
    assist.add_argument(
        "--no-vision",
        action="store_true",
        help="Read visible table text only, without vision configuration, recording, or clicks.",
    )
    play = browser_command("play", "Use vision and conservative autoplay while recording observations.")
    play.add_argument(
        "--hand-strength",
        action="store_true",
        help="Print the best confirmed hand on the flop, turn, and river.",
    )
    for command in (assist, play):
        command.add_argument(
            "strategy", nargs="?", choices=("conservative", "allin"), default="conservative",
            help="Decision policy: conservative by default, or preflop all-in with the premium range.",
        )
    browser_command("inspect", "Open Play Bots and save visible metadata/screenshots without poker actions.")
    args = parser.parse_args()

    if args.command is None:
        run_dry_run()
        return
    if args.command == "inspect":
        inspect_table(interval_seconds=args.interval, target_url=args.url)
        return

    auto_play = args.command == "play"
    vision = auto_play or not args.no_vision
    observe_table(
        interval_seconds=args.interval,
        target_url=args.url,
        record=vision,
        auto_play=auto_play,
        record_dom=False,
        vision=vision,
        hand_strength=args.hand_strength if auto_play else vision,
        strategy=args.strategy,
    )


if __name__ == "__main__":
    main()
