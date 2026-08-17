"""Shared browser configuration for Gambit integrations."""

from pathlib import Path


GAMBIT_URL = "https://gambit.com/"
PROFILE_DIRECTORY = Path(".browser-profile")


def validate_gambit_url(target_url: str | None) -> None:
    if target_url is not None and not target_url.startswith(GAMBIT_URL):
        raise ValueError("--url must be an https://gambit.com/ URL")
