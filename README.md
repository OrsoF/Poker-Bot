# Poker Bot

A visible-browser poker-table assistant for authorized Gambit tables.

The project reads only what is rendered in the browser. You sign in manually; it does not read credentials, browser storage, private APIs, or hidden table data. Use browser automation only where it is permitted and on tables you are authorized to control.

## Current strategy

The current policy is intentionally conservative and incomplete:

- Check when checking is free.
- Open only `AA`, `KK`, `QQ`, `JJ`, `AKs`, `AQs`, or `AKo` from a confirmed unopened preflop position.
- Fold all calls, re-raises, postflop betting decisions, and ambiguous states.

This is a safety baseline, not a claim of optimal poker play.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item config/vision.example.json config/vision.json
python -m src.main train
```

## Commands

| Command | Behavior |
| --- | --- |
| `python -m src.main` or `python -m src.main dry-run` | Exercises the safe policy without opening a browser. |
| `python -m src.main observe` | Opens a visible browser and reports table state; never clicks. |
| `python -m src.main inspect` | Saves visible DOM metadata and screenshots; never clicks. |
| `python -m src.main train` | Prompts to label unknown cards and saves local templates; never clicks. |
| `python -m src.main assist` | Shows vision and safe recommendations while you act manually. |
| `python -m src.main play` | Uses card vision and the safe autoplay policy. Add `--hand-strength` for display-only hand analysis. |

Browser commands accept `--interval SECONDS` and `--url https://gambit.com/...`.

```powershell
python -m src.main play --hand-strength --interval 1
```

## Structure

```text
src/
  main.py                    CLI entry point
  browser/                   Gambit session, table reading, controls, inspection, and training
  reader/                    Visible-text parsing and JSONL observation recording
  strategy/
    conservative.py          The only safe decision policy
  vision/                    DOM/screenshot card reads, layout, street detection, hand display
tests/                       Four scenario tests: browser safety, strategy, vision, application
config/vision.example.json   Template for local table calibration
data/                        Local observations and learned card templates
```

## Safety behavior

Actions require a stable actionable observation. Immediately before a click, the browser re-reads the visible hero-turn signal, legal controls, and displayed action amount. If anything changed, it cancels.

When DOM card data is incomplete, screenshot fallback captures once per unchanged hero turn and reuses that result. The cache resets when the turn, street, or card-slot layout changes.

Unknown cards, position, action amount, or inconsistent state fail closed to `CHECK`, `FOLD`, or `NO_ACTION`.

## Future work

1. Improve table-read reliability with calibrated vision and recorded fixtures for layout/parser variations.
2. Reduce noisy terminal output while retaining JSONL audit records.
3. Expand strategy one isolated rule at a time, starting with narrow preflop facing-open decisions.
4. Add postflop calls only after board, pot, price, player count, and effective-stack reads are reliable. Then evaluate PokerKit behind a small tested adapter.
5. Add explicit session controls: stop control, action/hand cap, loss cap, and structured decision/action logs.
6. Add a formatter, linter, dependency lockfile, and CI for the scenario tests.

## Development

```powershell
python -m pytest -q
```

See [AGENTS.md](AGENTS.md) for implementation boundaries and coding-agent guidance.
