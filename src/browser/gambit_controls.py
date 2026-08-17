"""Visible Gambit controls and their live numeric values."""

import re
from random import uniform
from time import sleep
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


FOLD_LABEL = re.compile(r"\bfold\b", re.IGNORECASE)
CALL_LABEL = re.compile(r"^Call:\s*\d+(?:\.\d+)?(?:\s*BB)?$", re.IGNORECASE)
RAISE_LABEL = re.compile(
    r"^(?:Check\s+)?(?:Bet|Raise):\s*\d+(?:\.\d+)?(?:\s*BB)?$",
    re.IGNORECASE,
)
POT_LABEL = re.compile(r"^(\d+(?:\.\d+)?)\s*BB$", re.IGNORECASE)


def visible_text_control(page: "Page", text: str | re.Pattern[str]):
    """Return the innermost visible control with the exact displayed text."""
    matches = page.get_by_text(text, exact=True).all()
    for candidate in reversed(matches):
        if candidate.is_visible():
            return candidate
    return None


def find_action_control(page: "Page", action: str):
    """Resolve one visible control from the live action panel."""
    if action != "RAISE" and visible_text_control(page, "All-In") is None:
        return None
    label = {
        "CHECK": "Check",
        "FOLD": "Fold",
        "RAISE": RAISE_LABEL,
    }.get(action, CALL_LABEL)
    return visible_text_control(page, label)


def live_call_amount(page: "Page") -> float | None:
    """Read the current Call button rather than historical page text."""
    control = find_action_control(page, "CALL")
    if control is None:
        return None
    match = CALL_LABEL.fullmatch(control.inner_text().strip())
    amount = re.search(r"\d+(?:\.\d+)?", match.group(0)) if match else None
    return float(amount.group(0)) if amount else None


def live_raise_amount(page: "Page") -> float | None:
    """Read the current Raise/Bet button rather than a sizing preset."""
    control = find_action_control(page, "RAISE")
    if control is None:
        return None
    match = RAISE_LABEL.fullmatch(control.inner_text().strip())
    amount = re.search(r"\d+(?:\.\d+)?", match.group(0)) if match else None
    return float(amount.group(0)) if amount else None


def live_pot_amount(page: "Page", layout) -> float | None:
    """Read the standalone pot label geometrically scoped above the board."""
    if not layout.board:
        return None
    left = min(region.x for region in layout.board)
    right = max(region.x + region.width for region in layout.board)
    top = min(region.y for region in layout.board)
    height = max(region.height for region in layout.board)
    labels = page.locator("*").evaluate_all(
        r"""(elements, region) => {
          const width = window.innerWidth, height = window.innerHeight;
          const left = region[0] * width, right = region[1] * width;
          const top = region[2] * height, bandTop = top - region[3] * height * 0.75;
          return elements.map((element) => {
            const text = (element.innerText || '').trim();
            const rect = element.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2;
            return {text, area: rect.width * rect.height,
              distance: Math.abs(centerX - (left + right) / 2)};
          }).filter(({text, area}, index) => {
            const rect = elements[index].getBoundingClientRect();
            const centerX = rect.x + rect.width / 2, centerY = rect.y + rect.height / 2;
            return /^\d+(?:\.\d+)?\s*BB$/i.test(text) && area > 0
              && centerX >= left && centerX <= right && centerY >= bandTop && centerY < top;
          }).sort((first, second) => first.area - second.area || first.distance - second.distance)
            .map(({text}) => text);
        }""",
        [left, right, top, height],
    )
    if not labels:
        return None
    match = POT_LABEL.fullmatch(labels[0])
    return float(match.group(1)) if match else None


def available_actions(page: "Page") -> frozenset[str]:
    """Return every action currently visible in the live action panel."""
    return frozenset(
        action
        for action in ("FOLD", "CHECK", "CALL", "RAISE")
        if find_action_control(page, action) is not None
    )


def click_next_hand(page: "Page") -> bool:
    """Advance through Gambit's visible post-hand control if it remains stable."""
    if visible_text_control(page, "Next Hand") is None:
        return False
    sleep(uniform(0, 1))
    control = visible_text_control(page, "Next Hand")
    if control is None:
        return False
    control.click(timeout=2_000)
    return True
