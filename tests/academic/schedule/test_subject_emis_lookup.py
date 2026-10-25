"""The EMIS id of a subject: the key that notebooks keep default materials under."""

from app.modules.academic.infrastructure.orm import Subject as SubjectRow
from app.modules.academic.infrastructure.schedule.reader import SqlScheduleReader
from app.shared.ids import new_id

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def physics(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> SubjectRow:
    """A subject with an EMIS id, stored in the test transaction."""
    row = SubjectRow(id=new_id(), emis_subject_id=4417, name={"en": "Physics"})
    async with sessionmaker_in_tx() as session:
        session.add(row)
        await session.commit()
    return row


async def test_a_subject_reports_its_emis_id(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession], physics: SubjectRow
) -> None:
    """The reader returns the EMIS id of a stored subject."""
    reader = SqlScheduleReader(sessionmaker_in_tx)

    assert await reader.subject_emis_id(physics.id) == 4417


async def test_an_unknown_subject_has_no_emis_id(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """A subject that is not in our database has no EMIS id here (None)."""
    reader = SqlScheduleReader(sessionmaker_in_tx)

    assert await reader.subject_emis_id(new_id()) is None
