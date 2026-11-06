"""Flash card argument models shared by the Students and LMS Course servers.

The models live in ``app.shared.contracts.lms_blocks`` (the course author assistant
uses them too). The MCP `CardList` has no count cap of its own: the per-set cap
(`MAX_CARDS_PER_SET`) is enforced by the flashcards module.
"""

from typing import Annotated

from app.shared.contracts.lms_blocks import (
    CardText,
    FlashcardInput,
    card_pairs,
)

from pydantic import Field

CardList = Annotated[
    list[FlashcardInput],
    Field(min_length=1, description="Cards to add, at least one."),
]

__all__ = ["CardList", "CardText", "FlashcardInput", "card_pairs"]
