# Poker Bot

A visible-browser poker-table assistant for authorized Gambit tables.

The project reads only what is rendered in the browser. You sign in manually; it does not read credentials, browser storage, private APIs, or hidden table data. Use browser automation only where it is permitted and on tables you are authorized to control.

## Current strategy

The current policy is intentionally conservative and incomplete:

- Check when checking is free.
- Open only `AA`, `KK`, `QQ`, `JJ`, `AKs`, `AQs`, or `AKo` from a confirmed unopened preflop position.
- Fold all calls, re-raises, postflop betting decisions, and ambiguous states.

This is a safety baseline, not a claim of optimal poker play.

The optional `allin` policy pushes `55+`, `A2s+`, `KTs+`, `QTs+`, `JTs`,
`ATo+`, and `KJo+` preflop regardless of position, prior raises, or stack size. Here `s`
means suited and `o` means offsuit. It pushes these hands even when checking is
free. Other hands and postflop decisions check when free or fold. Missing or inconsistent cards,
street, controls, or action amounts prevent an all-in.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

If `config/vision.json` is missing, copy `config/vision.example.json` to it.
Calibrate its card and ACTION-badge regions for your table view.

## Usage

Start with assistance while you play manually:

```powershell
python -m src.main assist
```

This reads cards, prompts you to label unknown cards, records observations, and
shows safe recommendations and hand strength. It never clicks table controls.

To enable the conservative autoplay policy:

```powershell
python -m src.main play
```

To select the preflop all-in policy:

```powershell
python -m src.main play allin
```

`play` without a strategy keeps the conservative policy. `assist allin`
previews all-in recommendations without clicking. Gambit's All-In sizing is
selected first, then the displayed Raise or All-In amount and table state are
rechecked before submission. Gambit can rename the third action button from
`Raise: amount` to `All-In: amount`; the separate Call button is not used to
submit that raise. If sizing cannot be confirmed for a preflop hand in its range,
the bot checks when free or waits without folding it automatically.

Both modes learn unknown cards during observation; no separate training command
is needed. `play` is the only mode that submits poker actions or advances hands.

On a complete six-player table, `SIÈGES` displays each player's name, position,
and visible stack in BB, including folded players. The yellow dealer `D` sets
BTN; the remaining seats receive SB, BB, UTG, HJ, and CO clockwise. The hero's
seat comes from the calibrated card regions. The moving `ACTION` badge only
identifies whose turn it is. Positions remain unknown if `D` is missing or
ambiguous; incomplete or ambiguous seating layouts are not assigned positions.
These reads continue on opponents' turns and are included in JSONL records.
Gambit's CSS-background images are supported even when the accompanying `img`
is transparent. Visible stacks and folded seats supply the hero stack, active
player count, and effective stack; missing stacks keep the effective stack unknown.

## Diagnostics and options

Use `assist --no-vision` to read table text without vision configuration,
recording, or clicks. For visible DOM metadata and screenshot exports:

```powershell
python -m src.main inspect
```

`inspect` opens Play Bots automatically once its button is visible. Sign in
manually if needed. It saves visible DOM metadata and screenshots without
submitting poker actions. With `--url`, it inspects that URL without opening
Play Bots. Repeated identical errors are printed once with their full message;
closing the browser page stops the inspector.

All three commands accept `--interval SECONDS` and `--url https://gambit.com/...`.
`play --hand-strength` also displays hand analysis.
Running `python -m src.main` without a command performs the offline decision
check without opening a browser.

## Structure

```text
src/
  main.py                    CLI entry point
  models.py                  Immutable poker state shared by readers and strategy
  browser/                   Gambit session, table reading, controls, inspection, and training
  reader/                    Visible-text parsing and JSONL observation recording
  strategy/
    conservative.py          Default conservative policy and strict opening range
    allin.py                 Optional preflop all-in policy with its own wider range
  vision/                    DOM/screenshot card reads, layout, street detection, hand display
tests/                       Scenario tests: browser safety, strategy, vision, application
config/vision.example.json   Template for local table calibration
data/                        Local observations and learned card templates
```

The table reader merges visible text, controls, and raw card reads into one
`ObservedState`. `TableObservation` carries that state together with source
evidence for stability checks, display, and training. Strategy consumes the
merged state directly. JSONL records retain the text audit input in `parsed`
and include the merged state in `observed`. With vision enabled, the terminal
shows a block for each stable decision: session hand number, street, cards,
known position/stacks, price, and a short explanation. Missing information is
explicitly marked `LECTURE INCOMPLÈTE`. Confirmed cards omit confidence scores;
the known-template count appears at startup and when it changes. `SIÈGES`
repeats when the dealer or seated players change. Intermediate states and
opponent turns still go to JSONL; decision records also retain the full policy
reason in `decision` and the session counter in `hand_number`.
`assist --no-vision` keeps the text-based `STATE` diagnostics.

## Safety behavior

Actions require a stable actionable observation. Immediately before a click, the browser re-reads the visible hero-turn signal, legal controls, and displayed action amount. If anything changed, it cancels.

When DOM card data is incomplete, screenshot fallback captures once per unchanged hero turn and reuses that result. The cache resets when the turn, street, or card-slot layout changes.

Unknown cards, position, action amount, or inconsistent state fail closed to `CHECK`, `FOLD`, or `NO_ACTION`.

## Future work

1. Improve table-read reliability with calibrated vision and recorded fixtures for layout/parser variations.
2. Improve the reliability of seat and stack reads using real DOM fixtures.
3. Expand strategy one isolated rule at a time, starting with narrow preflop facing-open decisions.
4. Add postflop calls only after board, pot, price, player count, and effective-stack reads are reliable. Then evaluate PokerKit behind a small tested adapter.
5. Add explicit session controls: stop control, action/hand cap, loss cap, and structured decision/action logs.
6. Add a formatter, linter, dependency lockfile, and CI for the scenario tests.

## Development

```powershell
python -m pytest -q
```

See [AGENTS.md](AGENTS.md) for implementation boundaries and coding-agent guidance.
