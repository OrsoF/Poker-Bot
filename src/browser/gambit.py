"""Visible, user-authenticated table observer.

The only supported action is an explicitly enabled click on a button whose
accessible label is "Fold".  Keep selectors here, never in strategy code.
"""

from pathlib import Path
from random import uniform
from time import sleep
from typing import TYPE_CHECKING
import re
from dataclasses import replace

from src.reader.game_state import parse_visible_state
from src.reader.recorder import ObservationRecorder
from src.strategy.conservative import recommend, with_vision_hand

if TYPE_CHECKING:
    from playwright.sync_api import Page


GAMBIT_URL = "https://gambit.com/"
PROFILE_DIRECTORY = Path(".browser-profile")
# Gambit may add an accessible keyboard hint, e.g. "Fold (F)".
FOLD_LABEL = re.compile(r"\bfold\b", re.IGNORECASE)
CALL_LABEL = re.compile(r"^Call:\s*\d+(?:\.\d+)?(?:\s*BB)?$", re.IGNORECASE)


def _table_summary(page: "Page") -> str:
    """Return a compact, visible-text snapshot without inspecting browser storage."""
    text = page.locator("body").inner_text(timeout=2_000)
    return " ".join(text.split())[:500]


def _fold_button_is_ready(page: "Page") -> bool:
    """Detect an actionable Fold button using its user-visible accessible name."""
    return _find_fold_control(page) is not None


def _fold(page: "Page") -> bool:
    """Click only the action that was confirmed ready in this UI frame."""
    sleep(uniform(0, 1))
    fold = _find_fold_control(page)
    if fold is None:
        return False
    fold.click(timeout=2_000)
    return True


def _next_hand_if_available(page: "Page") -> bool:
    """Advance only through Gambit's one visible post-hand control."""
    next_hand = _visible_text_control(page, "Next Hand")
    if next_hand is not None:
        sleep(uniform(0, 1))
        # Re-resolve after the pause because the table can update quickly.
        next_hand = _visible_text_control(page, "Next Hand")
        if next_hand is None:
            return False
        next_hand.click(timeout=2_000)
        return True
    return False


def _find_action_control(page: "Page", action: str):
    """Resolve exactly one visible live action control by its displayed label."""
    if _visible_text_control(page, "All-In") is None:
        return None
    label = {"CHECK": "Check", "FOLD": "Fold"}.get(action)
    return _visible_text_control(
        page,
        label if label is not None else CALL_LABEL,
    )


def _visible_text_control(page: "Page", text: str | re.Pattern[str]):
    """Choose the innermost visible match from Gambit's nested custom controls."""
    matches = page.get_by_text(text, exact=True).all()
    for candidate in reversed(matches):
        if candidate.is_visible():
            return candidate
    return None


def _visible_dom_map(page: "Page") -> dict[str, object]:
    """Capture visible UI metadata only, for stable selector discovery."""
    extractor = """(elements) => elements.filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
    }).map((element) => ({
      tag: element.tagName.toLowerCase(),
      text: (element.innerText || element.value || '').trim().slice(0, 120),
      role: element.getAttribute('role'),
      ariaLabel: element.getAttribute('aria-label'),
      title: element.getAttribute('title'),
      testId: element.getAttribute('data-testid'),
      disabled: element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true',
      data: Object.fromEntries(Array.from(element.attributes)
        .filter((attribute) => attribute.name.startsWith('data-'))
        .map((attribute) => [attribute.name, attribute.value])),
    }))"""
    controls = page.locator("button, [role='button'], input[type='button'], input[type='submit']").evaluate_all(extractor)
    cards = page.locator("img, [aria-label*='card' i], [data-card]").evaluate_all(
        """(elements) => elements.filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        }).map((element) => ({
          tag: element.tagName.toLowerCase(), alt: element.getAttribute('alt'),
          ariaLabel: element.getAttribute('aria-label'),
          srcTail: (() => { const src = element.getAttribute('src') || '';
            return src.startsWith('data:') ? 'inline-data-image' : src.split('?')[0].split('/').pop(); })(),
          className: element.className || null,
        }))"""
    )
    action_candidates = page.locator("*").evaluate_all(
        """(elements) => elements.filter((element) => {
          const text = (element.innerText || '').trim();
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0
            && /^(Fold|Check|Next Hand|Call:\\s*\\d+|Raise:\\s*\\d+)$/.test(text);
        }).map((element) => ({
          tag: element.tagName.toLowerCase(), text: element.innerText.trim(),
          className: element.className || null, role: element.getAttribute('role'),
          ariaLabel: element.getAttribute('aria-label'),
          attributes: Object.fromEntries(Array.from(element.attributes)
            .filter((attribute) => attribute.name === 'id' || attribute.name === 'type' || attribute.name.startsWith('data-'))
            .map((attribute) => [attribute.name, attribute.value])),
          parent: {tag: element.parentElement?.tagName.toLowerCase() || null,
            className: element.parentElement?.className || null},
        }))"""
    )
    return {
        "controls": controls,
        "action_candidates": action_candidates,
        "card_candidates": cards,
    }


def _apply_conservative_action(page: "Page", action: str) -> bool:
    """Click a revalidated conservative action after a short random delay."""
    control = _find_action_control(page, action)
    if control is None:
        return False
    sleep(uniform(0, 1))
    control = _find_action_control(page, action)
    if control is None:
        return False
    control.click(timeout=2_000)
    print(f"ACTION: {action.title()} clicked")
    return True


def _print_vision_state(screenshot: bytes, vision_reader, state, stage: str | None) -> None:
    from src.vision.capture import save_screenshot

    screenshot_path = save_screenshot(screenshot)
    hero_confirmed = sum(card.card is not None for card in state.hero)
    board_confirmed = sum(card.card is not None for card in state.board)
    print(
        "TURN: "
        f"cards={vision_reader.matcher.card_count}/52 "
        f"samples={vision_reader.matcher.template_count} "
        f"stage={stage or '?'} "
        f"hero={hero_confirmed}/{len(state.hero)} [{_format_card_reads(state.hero)}] "
        f"board={board_confirmed}/{len(state.board)} [{_format_card_reads(state.board)}]"
    )
    print(f"CAPTURE: {screenshot_path}")


def _format_card_reads(cards) -> str:
    """Show accepted cards and the best candidate for low-confidence matches."""
    parts = []
    for card in cards:
        label = "empty" if card.is_empty else card.card or f"{card.candidate or '?'}?"
        parts.append(f"{label} {card.confidence:.0%}")
    return ", ".join(parts) or "none"


def _state_summary(state) -> str:
    """Produce a stable terminal summary without dumping all visible page text."""
    call = "?" if state.to_call is None else f"{state.to_call:g} BB"
    return f"street={state.street or '?'} call={call} check={'yes' if state.can_check else 'no'}"


def _find_fold_control(page: "Page"):
    """Find one visible interactive Fold control, never plain table-history text."""
    candidates = (
        page.get_by_role("button", name=FOLD_LABEL),
        page.locator("button").filter(has_text=FOLD_LABEL),
        page.locator("[role='button']").filter(has_text=FOLD_LABEL),
    )
    for candidate in candidates:
        if candidate.count() == 1 and candidate.is_visible() and candidate.is_enabled():
            return candidate

    # Gambit's table currently renders its action controls with a custom
    # clickable element, without a button tag or ARIA role. Restrict this text
    # fallback to the live action panel: historical actions use uppercase FOLD
    # and the panel disappears after the hand resolves.
    live_action_panel = _visible_text_control(page, "All-In")
    text_control = _visible_text_control(page, "Fold")
    if live_action_panel is not None and text_control is not None:
        return text_control
    return None


def _print_state(
    page: "Page",
    previous: str,
    strategy: str,
    recorder: ObservationRecorder | None,
    record_dom: bool,
    hero_turn: bool,
) -> str:
    raw_text = page.locator("body").inner_text(timeout=2_000)
    summary = " ".join(raw_text.split())[:500]
    if summary != previous:
        state = parse_visible_state(raw_text)
        print(f"STATE: {_state_summary(state)} hero_turn={'yes' if hero_turn else 'no'}")
        if strategy == "conservative" or recorder is not None:
            if recorder is not None:
                recorder.write(
                    raw_text,
                    state,
                    hero_turn=hero_turn,
                    dom_map=_visible_dom_map(page) if record_dom else None,
                )
            if strategy == "conservative":
                decision = recommend(state)
                print(f"DECISION: {decision.action} — {decision.reason}")
    return summary


def _observe_once(
    page: "Page",
    auto_fold: bool,
    fold_was_ready: bool,
    waiting_for_next_hand: bool,
) -> tuple[bool, bool]:
    """Run one polling cycle and return Fold and post-fold state.

    The transition guard prevents repeated clicks against the same turn while a
    slow page is still rendering its result.
    """
    if waiting_for_next_hand and _next_hand_if_available(page):
        print("ACTION: Next Hand clicked")
        return False, False
    if waiting_for_next_hand:
        # The action panel remains visible while other players finish the hand.
        # Do not inspect it again until our post-fold Next Hand control appears.
        return False, True

    fold_is_ready = _fold_button_is_ready(page)
    if auto_fold and fold_is_ready and not fold_was_ready:
        if _fold(page):
            print("ACTION: Fold clicked")
            return False, True
        print("WAIT: Fold control changed before click")
        return False, False
    return fold_is_ready, waiting_for_next_hand


def observe_table(
    auto_fold: bool,
    interval_seconds: float,
    target_url: str | None = None,
    strategy: str = "fold-only",
    record: bool = False,
    auto_play: bool = False,
    record_dom: bool = False,
    vision: bool = False,
) -> None:
    """Open a headed browser and print state changes until Ctrl+C is pressed."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    if target_url is not None and not target_url.startswith("https://gambit.com/"):
        raise ValueError("--url must be an https://gambit.com/ URL")

    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install -r requirements.txt"
        ) from error

    vision_reader = None
    if vision or auto_play:
        from src.vision.layout import load_layout
        from src.vision.reader import VisionReader

        layout = load_layout()
        if layout is None:
            raise RuntimeError(
                "Vision needs config/vision.json. Copy config/vision.example.json and calibrate it first."
            )
        vision_reader = VisionReader(layout)
        from src.vision.stage import StableStageDetector
        stage_detector = StableStageDetector()

    PROFILE_DIRECTORY.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIRECTORY.resolve()),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url or GAMBIT_URL, wait_until="domcontentloaded")
        print("Browser open. Sign in manually, navigate to your table, then watch this terminal.")
        recorder = ObservationRecorder() if record else None
        if recorder is not None:
            print(f"Recording visible state changes to: {recorder.path}")

        previous = ""
        auto_turn_active = False
        vision_turn_active = False
        fold_was_ready = False
        waiting_for_next_hand = False
        try:
            while True:
                try:
                    screenshot = page.screenshot() if vision_reader is not None else None
                    vision_state = vision_reader.read_screenshot(screenshot) if screenshot is not None else None
                    stage = stage_detector.observe(vision_state.board) if vision_state is not None else None
                    hero_turn = False
                    if screenshot is not None:
                        from src.vision.turn import is_hero_turn
                        hero_turn = is_hero_turn(screenshot, vision_reader.layout)
                    previous = _print_state(page, previous, strategy, recorder, record_dom, hero_turn)
                    if auto_play and _next_hand_if_available(page):
                        print("ACTION: Next Hand clicked")
                        auto_turn_active = False
                        sleep(interval_seconds)
                        continue
                    raw_text = page.locator("body").inner_text(timeout=2_000)
                    if vision and screenshot is not None and hero_turn and not vision_turn_active:
                        _print_vision_state(screenshot, vision_reader, vision_state, stage)
                        vision_turn_active = True
                    if not hero_turn:
                        vision_turn_active = False
                    if auto_play and hero_turn:
                        if not auto_turn_active:
                            decision_state = with_vision_hand(
                                parse_visible_state(raw_text, read_coaching_hand=False),
                                vision_state.hero_cards,
                            )
                            # Text can contain coaching prose such as "check it";
                            # only the actual visible control determines whether
                            # checking is legal for an automatic action.
                            decision_state = replace(
                                decision_state,
                                street=stage,
                                can_check=_find_action_control(page, "CHECK") is not None,
                            )
                            decision = recommend(decision_state)
                            if decision.action in {"FOLD", "CHECK", "CALL"}:
                                if _apply_conservative_action(page, decision.action):
                                    auto_turn_active = True
                    if not hero_turn:
                        auto_turn_active = False
                    fold_was_ready, waiting_for_next_hand = _observe_once(
                        page,
                        auto_fold,
                        fold_was_ready,
                        waiting_for_next_hand,
                    )
                except Error as error:
                    # Tables can briefly re-render between polls; keep observing.
                    print(f"WAIT: {error.__class__.__name__}")
                    fold_was_ready = False
                sleep(interval_seconds)
        except KeyboardInterrupt:
            print("Observer stopped.")
        finally:
            context.close()
