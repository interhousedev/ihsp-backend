"""Personal-data specification of the flashcards module (export and erasure)."""

from app.modules.flashcards.infrastructure.orm.flashcard import Flashcard
from app.modules.flashcards.infrastructure.orm.flashcard_review import FlashcardReview
from app.modules.flashcards.infrastructure.orm.flashcard_set import FlashcardSet
from app.shared.personal_data import (
    ParentLink,
    PersonalTable,
    SqlPersonalData,
    Treatment,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E, N, R = Treatment.ERASE, Treatment.NULLIFY, Treatment.RETAIN
_ = ParentLink

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(FlashcardReview, E, owner="user_id"),
    PersonalTable(Flashcard, E, parent=ParentLink(FlashcardSet, "set_id", "owner_id")),
    PersonalTable(FlashcardSet, E, owner="owner_id"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
