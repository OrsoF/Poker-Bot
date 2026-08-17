"""Read-only browser inspector for selector and layout diagnostics."""

import json
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING

from src.browser.gambit_config import GAMBIT_URL, PROFILE_DIRECTORY, validate_gambit_url

if TYPE_CHECKING:
    from playwright.sync_api import Page


def visible_dom_map(page: "Page") -> dict[str, object]:
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
      rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
    }))"""
    controls = page.locator("button, [role='button'], input[type='button'], input[type='submit']").evaluate_all(extractor)
    cards = page.locator("body").evaluate(
        """(body) => {
          const visible = (element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const description = (element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const source = element.getAttribute('src') || element.getAttribute('srcset') || '';
            const classes = typeof element.className === 'string' ? element.className : '';
            return {
              tag: element.tagName.toLowerCase(), id: element.id || null,
              className: classes || null, role: element.getAttribute('role'),
              alt: element.getAttribute('alt'), ariaLabel: element.getAttribute('aria-label'),
              text: (element.innerText || '').trim().slice(0, 300) || null,
              attributes: Object.fromEntries(Array.from(element.attributes).map((attribute) => [attribute.name, attribute.value])),
              source: source.startsWith('data:') ? 'inline-data-image' : source.slice(0, 500) || null,
              rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
              style: {backgroundImage: style.backgroundImage, backgroundSize: style.backgroundSize,
                backgroundPosition: style.backgroundPosition, transform: style.transform,
                opacity: style.opacity, objectFit: style.objectFit},
              html: element.outerHTML.slice(0, 4000),
              ancestors: Array.from({length: 3}, (_, index) => {
                let parent = element;
                for (let step = 0; step <= index; step += 1) parent = parent?.parentElement;
                return parent ? {tag: parent.tagName.toLowerCase(), id: parent.id || null,
                  className: typeof parent.className === 'string' ? parent.className || null : null,
                  attributes: Object.fromEntries(Array.from(parent.attributes).map((attribute) => [attribute.name, attribute.value])),
                  html: parent.outerHTML.slice(0, 2000)} : null;
              }).filter(Boolean),
            };
          };
          const candidates = new Set();
          body.querySelectorAll("img, svg, canvas, [aria-label*='card' i], [data-card], [class*='card' i], [id*='card' i]")
            .forEach((element) => candidates.add(element));
          return Array.from(candidates).filter(visible).map(description);
        }"""
    )
    tables = page.locator("body").evaluate(
        """(body) => Array.from(body.querySelectorAll("[class*='table' i], [id*='table' i], [data-testid*='table' i]"))
          .filter((element) => { const rect = element.getBoundingClientRect(); return rect.width > 0 && rect.height > 0; })
          .map((element) => ({tag: element.tagName.toLowerCase(), id: element.id || null,
            className: typeof element.className === 'string' ? element.className || null : null,
            attributes: Object.fromEntries(Array.from(element.attributes).map((attribute) => [attribute.name, attribute.value])),
            html: element.outerHTML.slice(0, 12000)}))"""
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
        "table_candidates": tables,
    }


def inspect_table(interval_seconds: float, target_url: str | None = None) -> None:
    """Save visible table metadata and screenshots without clicking any controls."""
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

    directory = Path("data/inspections")
    directory.mkdir(parents=True, exist_ok=True)
    PROFILE_DIRECTORY.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIRECTORY.resolve()),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url or GAMBIT_URL, wait_until="domcontentloaded")
        print("Inspector open. Sign in and navigate to a table; no table actions will be taken.")
        previous = ""
        try:
            while True:
                try:
                    visible_text = page.locator("body").inner_text(timeout=2_000)
                    dom = visible_dom_map(page)
                    fingerprint = json.dumps({"text": visible_text, "dom": dom}, sort_keys=True)
                    if fingerprint != previous:
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                        screenshot_path = directory / f"gambit-{stamp}.png"
                        metadata_path = directory / f"gambit-{stamp}.json"
                        page.screenshot(path=str(screenshot_path))
                        metadata_path.write_text(
                            json.dumps(
                                {
                                    "captured_at": datetime.now().astimezone().isoformat(),
                                    "url": page.url,
                                    "visible_text": visible_text,
                                    "visible_dom": dom,
                                    "screenshot": screenshot_path.name,
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        print(f"INSPECTION: saved {metadata_path}")
                        previous = fingerprint
                except Error as error:
                    print(f"WAIT: {error.__class__.__name__}")
                sleep(interval_seconds)
        except KeyboardInterrupt:
            print("Inspector stopped.")
        finally:
            context.close()
