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

## Commands

Install the browser runtime once after installing dependencies:

```powershell
python -m playwright install chromium
python -m src.main observe
```

A visible Chromium window opens. Sign in yourself; credentials are never read,
saved, or placed in this project. The same local browser profile is reused for
later sessions.

| Command | Behaviour |
| --- | --- |
| `python -m src.main` or `python -m src.main dry-run` | Runs the offline mock-table dry run. |
| `python -m src.main observe` | Opens the visible observer; no screenshots or clicks. |
| `python -m src.main inspect` | Saves visible card/control metadata and screenshots to `data/inspections/`; never clicks. |
| `python -m src.main train` | Records screenshots and prompts for labels for unrecognized or low-confidence cards; never clicks. |
| `python -m src.main assist` | Shows card vision, hand strength, and conservative recommendations while you click actions yourself; prompts for unrecognized or low-confidence cards. |
| `python -m src.main play` | Uses vision and conservative autoplay while recording observations. Add `--hand-strength` to print the best confirmed hand on each street. |

Use it only where browser automation is allowed by the platform and for a
table you are authorized to control. Sign in yourself; credentials are never
read, saved, or placed in this project.

Each recorded observation includes a `hero_turn` field. The current turn gate
detects Gambit's blue `ACTION` badge in the calibrated hero-card region; it
does not rely on Gambit's coaching text.

Automatic calls fail closed unless confirmed cards, pot, call price, effective
stack, and active-player count remain stable. The conservative call gate uses
deterministic showdown sampling, pot odds, an equity-realization discount, and
requires the hole cards to contribute a made hand or confirmed draw postflop.

Browser commands accept these options:

```text
--interval SECONDS       Polling interval (default: 1.0)
--url https://gambit.com/...  Open a specific Gambit page or table URL
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
python -m src.main train
```

Hero and board cards use Gambit's visible inline SVG faces and are labelled
interactively the first time each face appears. Screenshots are used only when
the DOM card faces are unavailable.

Screenshot fallback saves its attempted reads in `data/observations/vision/`.
