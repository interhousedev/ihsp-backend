"""Shared pieces of the flash card write tools."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_CARDS = 100
PREVIEW_CARDS = 50
Side = Annotated[str, Field(min_length=1, max_length=2000)]


class CardArg(BaseModel):
    """One card the model wants to create."""

    model_config = ConfigDict(extra="forbid")

    front: Side
    back: Side


def card_items(cards: list[CardArg]) -> list[str]:
    """Return the preview lines of the first cards, then how many are not shown."""
    lines = [f"{card.front} → {card.back}" for card in cards[:PREVIEW_CARDS]]
    if len(cards) > PREVIEW_CARDS:
        lines.append(f"… +{len(cards) - PREVIEW_CARDS}")
    return lines
