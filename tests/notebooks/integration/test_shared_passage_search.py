"""Shared passage search against Postgres: no passage of a private notebook leaks."""

from app.modules.notebooks.application.shared_passage_search import (
    SharedPassageSearch,
)
from app.modules.notebooks.infrastructure.repositories.shared_passage_repository import (  # noqa: E501
    SqlSharedPassageReader,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SECRET = "Quantum chromodynamics diary: my private notes about gluon confinement."


def search_for(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SharedPassageSearch:
    """The use case over the real reader (no library, lessons or embeddings)."""
    return SharedPassageSearch(
        reader=SqlSharedPassageReader(sessionmaker),
        library=None,
        schedule=None,
        embeddings=None,
    )


async def test_other_students_private_passage_is_not_returned(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    student: Actor,
    other_student: Actor,
) -> None:
    """A passage of another student's notebook is invisible; the owner finds it."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, theirs, texts=(SECRET,))
    search = search_for(sessionmaker_in_tx)

    assert await search.execute(student, "gluon confinement", 10) == []
    mine = await search.execute(other_student, "gluon confinement", 10)
    assert [p.text for p in mine] == [SECRET]


async def test_same_text_added_by_both_is_found_through_own_source_only(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    student: Actor,
    other_student: Actor,
) -> None:
    """Two students hold one shared document; each gets it via their own source."""
    first = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, first, texts=(SECRET,))
    second = await make_notebook(uow_factory, student.user_id)
    mine = await make_source(uow_factory, second, texts=(SECRET,))

    found = await search_for(sessionmaker_in_tx).execute(student, "gluon", 10)

    assert [(p.source_id, p.notebook_id) for p in found] == [(mine.id, second.id)]
