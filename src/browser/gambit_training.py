"""Interactive card-template training during a live table read."""

from src.browser.gambit_observation import GambitTableReader, TableObservation
from src.vision.reader import VisionState
from src.vision.training import prompt_for_unknown_cards, prompt_for_unknown_dom_cards


def train_unknown_cards(
    observation: TableObservation,
    table_reader: GambitTableReader,
    vision_reader,
    dom_card_matcher,
    prompted_cards: set[str],
) -> TableObservation:
    """Prompt for unknown cards and return a fresh read if templates changed."""
    saved_dom_cards = prompt_for_unknown_dom_cards(
        observation.hero_sources,
        dom_card_matcher,
        prompted_cards,
        locations=("hero-1", "hero-2"),
    ) + prompt_for_unknown_dom_cards(
        observation.board_sources,
        dom_card_matcher,
        prompted_cards,
        locations=("board-1", "board-2", "board-3", "board-4", "board-5"),
    )
    has_dom_hero = bool(observation.hero_sources) and all(
        source is not None for source in observation.hero_sources
    )
    screenshot_skip_locations = (
        frozenset({"hero-1", "hero-2"})
        | frozenset(
            f"board-{index + 1}"
            for index, source in enumerate(observation.board_sources)
            if source is not None
        )
        if has_dom_hero
        else frozenset()
    )
    saved_screenshot_cards = (
        0
        if observation.screenshot is None
        else prompt_for_unknown_cards(
            observation.screenshot,
            vision_reader,
            VisionState(hero=observation.hero_reads, board=observation.board_reads),
            prompted_cards,
            skip_locations=screenshot_skip_locations,
        )
    )
    if saved_dom_cards or saved_screenshot_cards:
        return table_reader.read()
    return observation
