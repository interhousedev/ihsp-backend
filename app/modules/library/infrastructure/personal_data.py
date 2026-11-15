"""Personal-data specification of the library module (export and erasure)."""

from app.modules.library.infrastructure.orm.item import Item, MaterialDetails
from app.modules.library.infrastructure.orm.labels import ItemAuthor
from app.modules.library.infrastructure.orm.moderation import (
    BookSuggestion,
    ItemEvent,
    ItemReport,
    Sanction,
)
from app.modules.library.infrastructure.orm.reader import (
    Annotation,
    LessonItemRef,
    ReaderMarkup,
    ReadingProgress,
    ShelfEntry,
)
from app.modules.library.infrastructure.orm.taxonomy import ReadingList
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
    PersonalTable(
        Annotation, E, owner="user_id", note="erased by library.delete_owner"
    ),
    PersonalTable(
        ReadingProgress, E, owner="user_id", note="erased by library.delete_owner"
    ),
    PersonalTable(
        ShelfEntry, E, owner="user_id", note="erased by library.delete_owner"
    ),
    PersonalTable(
        ReaderMarkup, E, owner="user_id", note="erased by library.delete_owner"
    ),
    PersonalTable(BookSuggestion, E, owner="user_id"),
    PersonalTable(Sanction, E, owner="user_id"),
    PersonalTable(ReadingList, E, owner="owner_id"),
    PersonalTable(ItemEvent, R, owner="actor_id", note="catalogue history"),
    PersonalTable(ItemReport, R, owner="reporter_id", note="moderation record"),
    PersonalTable(Item, R, owner="owner_id", note="catalogue"),
    PersonalTable(MaterialDetails, R, owner="uploader_id", note="catalogue"),
    PersonalTable(ItemAuthor, R, owner="author_id", note="catalogue"),
    PersonalTable(LessonItemRef, R, owner="set_by", note="teacher plan"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
