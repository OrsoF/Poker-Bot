# Agent guide

## Repository purpose

Poker Bot is a visible-browser assistant for authorized Gambit poker tables.
It reads rendered page content only. The user signs in manually; never add
credential handling, private API calls, browser-storage reads, or hidden-state
access.

The default strategy is deliberately strict: check when free, open only a
small premium range in a confirmed unopened preflop position, and otherwise
fold. Treat this as a safety baseline rather than a complete poker strategy.
The explicitly selected `allin` policy pushes its own wider range (`55+`,
`A2s+`, `KTs+`, `QTs+`, `JTs`, `ATo+`, `KJo+`) preflop regardless of position, previous
raises, or stack size, including when checking is free.
Other hands and postflop spots check when free or fold.

## Architecture

- `src/main.py`: CLI entry point.
- `src/models.py`: immutable poker state shared by readers, recording, and strategy.
- `src/browser/`: Gambit-specific Playwright session, DOM controls, table
  observation, read-only inspection, and card-template training.
- `src/reader/`: visible-text parsing and JSONL observation recording.
- `src/strategy/`: pure decision policies consuming domain state. `conservative.py`
  owns the default policy, recommendation type, and strict opening range;
  `allin.py` owns the opt-in preflop policy and its wider range. Keep both
  independent from Playwright and Gambit selectors.
- `src/vision/`: DOM/SVG and screenshot card reading, calibrated layout,
  street detection, and display-only hand evaluation.
- `tests/`: scenario tests; avoid adding many micro-tests.
- `config/vision.example.json`: local vision-layout template. Never commit a
  user-specific `config/vision.json` or browser profile.

## Non-negotiable safety rules

1. Act only from a stable actionable observation.
2. Immediately before a click, re-read visible hero turn, legal actions, and
   the displayed call/raise amount. Cancel when they differ.
3. Missing cards, street, action amount, or inconsistent state must fail closed
   to `CHECK`, `FOLD`, or `NO_ACTION`. The conservative opening policy also
   requires position; the user explicitly permits unknown position for `allin`.
4. Screenshot fallback is turn-gated and cached once per unchanged hero turn.
   Reset the cache when hero turn ends or street/card-slot layout changes.
5. Keep all browser actions visibly user-authenticated and scoped to Gambit.

## Change guidelines

- Keep platform-specific selectors and browser behavior in `src/browser/`.
- Keep poker decisions pure and deterministic in `src/strategy/`.
- Prefer one small, explicit strategy rule over broad solver-like behavior.
- Do not add calls, re-raises, or postflop bets without confirmed inputs,
  explicit amount handling, a fail-closed path, and a scenario test.
- Keep terminal output decision-focused; persist detailed audit data in JSONL.
- Preserve user changes in a dirty worktree. Do not reset or discard files.

## Verification

Run after relevant changes:

```powershell
python -m pytest -q
$files = rg --files src tests -g '*.py'; python -m py_compile $files
git diff --check
```

## Near-term roadmap

1. Improve vision calibration and collect real table fixtures.
2. Reduce noisy state logging while preserving audit records.
3. Add strategy rules one at a time, beginning with narrow preflop spots.
4. Consider a PokerKit adapter only after table inputs are reliable and a
   specific equity-based decision is scoped.
5. Add session caps, a clear stop control, and structured action auditing
   before widening autoplay.
