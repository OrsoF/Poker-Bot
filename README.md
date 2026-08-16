# Poker Bot

Small, deliberately incomplete foundation for experimenting with poker decision
logic. The default runner uses an offline mock table; it does not connect to a
website or place wagers.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

`src/browser/` is an adapter boundary. If a platform explicitly allows browser
automation, keep its UI selectors and implementation there; keep strategy code
independent from the site.

## Visible observation mode

Install the browser runtime once after installing dependencies:

```powershell
python -m playwright install chromium
python -m src.main --observe
```

A visible Chromium window opens. Sign in yourself; credentials are never read,
saved, or placed in this project. The same local browser profile is reused for
later sessions.

## Commands

| Command | Behaviour |
| --- | --- |
| `python -m src.main` | Runs the offline mock-table dry run. |
| `python -m src.main --observe` | Opens the visible Gambit observer; no actions are taken. |
| `python -m src.main --observe --strategy fold-only --auto-fold` | Legacy test mode: folds every detected turn, then clicks Next Hand. |
| `python -m src.main --observe --strategy conservative` | Shadow mode: prints the conservative strategy recommendation without clicking. |
| `python -m src.main --observe --strategy conservative --record` | Shadow mode plus JSONL recording to `data/observations/`. |
| `python -m src.main --observe --strategy conservative --record --record-dom` | Recording plus visible UI metadata used to map stable table selectors. |
| `python -m src.main --observe --strategy conservative --vision` | Takes a table screenshot at a detected turn and reports high-confidence configured card reads. |
| `python -m src.main --observe --strategy conservative --auto-play --record` | Conservative auto-play plus recording. It folds unknown/non-premium preflop hands, checks when free, calls premium preflop hands and post-flop calls up to 2 BB, then clicks Next Hand when available. |

The recommended command while improving the parser is:

```powershell
python -m src.main --observe --strategy conservative --auto-play --record
```

Use it only where browser automation is allowed by the platform and for a
table you are authorized to control. Sign in yourself; credentials are never
read, saved, or placed in this project.

Each recorded observation includes a `hero_turn` field. The current turn gate
detects Gambit's blue `ACTION` badge in the calibrated hero-card region; it
does not rely on Gambit's coaching text.

Useful options:

```text
--interval SECONDS       Polling interval (default: 1.0)
--url https://gambit.com/...  Open a specific Gambit page or table URL
--record                 Save visible state changes for parser tuning
--record-dom             Include visible control and card-candidate metadata (requires --record)
--vision                 Enable local screenshot card recognition
```

## Vision setup

The table uses image-only cards, so vision is opt-in and defaults to no action.
Install the new dependencies, copy `config/vision.example.json` to
`config/vision.json`, then calibrate the normalized card rectangles for your
browser window. Save complete card-face reference crops as files named like
`As.png`, `Td.png`, and `7h.png` in `data/card_templates/`.

```powershell
pip install -r requirements.txt
Copy-Item config/vision.example.json config/vision.json
python -m src.main --observe --strategy conservative --vision
```

Only reads at least 92% template confidence are reported; unknown cards remain
`?` and are never used for decisions.

Vision mode also saves the screenshot used for each attempted read in
`data/observations/vision/`; use those images to calibrate the rectangles and
create the card templates.
