"""Onboarding tour after linking: steps navigate and callbacks stay small."""

from app.interfaces.bot.callbacks import OnboardingCb
from app.interfaces.bot.keyboards.onboarding import STEPS
from tests.bot.support.harness import Harness

import pytest


@pytest.mark.parametrize("step", STEPS)
async def test_every_step_shows_its_text(harness: Harness, step: str) -> None:
    """Each step edits the message to its own text."""
    await harness.press(OnboardingCb(step=step).pack())

    assert harness.last_text().startswith(f"onboarding-{step}")


async def test_next_and_back_walk_the_tour(harness: Harness) -> None:
    """Next goes forward, Back returns, the last step ends in the menu."""
    await harness.press("ob:welcome")
    assert "ob:apps" in harness.last_callbacks()
    await harness.press("ob:apps")
    assert "ob:welcome" in harness.last_callbacks()
    assert "ob:settings" in harness.last_callbacks()
    await harness.press("ob:ai")
    assert "m:menu" in harness.last_callbacks()
    assert "ob:settings" in harness.last_callbacks()


async def test_apps_step_links_the_apps_of_the_role(harness: Harness) -> None:
    """A student gets web app buttons for the school, courses and library."""
    await harness.press("ob:apps")

    labels = harness.last_labels()
    assert "onboarding-app-sp" in labels
    assert "onboarding-app-library" in labels


def test_callback_data_fits_telegram() -> None:
    """Every step packs to at most 64 bytes."""
    assert all(len(OnboardingCb(step=s).pack().encode()) <= 64 for s in STEPS)
