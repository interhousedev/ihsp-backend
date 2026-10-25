"""Flash card argument models shared by the Students and LMS Course servers.

The models live in ``app.shared.contracts.lms_blocks`` (the course author assistant
uses them too).
"""

from app.shared.contracts.lms_blocks import (
    CardList,
    CardText,
    FlashcardInput,
    card_pairs,
)

__all__ = ["CardList", "CardText", "FlashcardInput", "card_pairs"]
