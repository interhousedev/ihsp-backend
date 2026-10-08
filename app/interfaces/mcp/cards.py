"""Flash card argument models shared by the Students and LMS Course servers."""

from typing import Annotated

from pydantic import BaseModel, Field

CardText = Annotated[str, Field(min_length=1, max_length=2000)]


class FlashcardInput(BaseModel):
    """One flash card to create."""

    front: CardText = Field(description="Question side of the card.")
    back: CardText = Field(description="Answer side of the card.")


CardList = Annotated[
    list[FlashcardInput],
    Field(min_length=1, max_length=200, description="Cards to add (at most 200)."),
]


def card_pairs(cards: list[FlashcardInput]) -> list[tuple[str, str]]:
    """Convert card inputs to the (front, back) pairs FlashcardsApi takes."""
    return [(card.front, card.back) for card in cards]
