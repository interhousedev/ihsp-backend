"""Essays sealed under a key that is gone or changed: listed as unreadable."""

import os
from uuid import UUID

from app.bootstrap import common  # noqa: F401  (registers every model)
from app.modules.admission.domain.essay_categories import ShortAnswer
from app.modules.admission.domain.essays import Essay, EssayIdea
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.modules.admission.infrastructure.essay_flow_repository import (
    SqlShortAnswerRepository,
)
from app.modules.admission.infrastructure.essays_repository import SqlEssayRepository
from app.modules.admission.ports.essay_crypto import KEY_BYTES, EssayKey
from app.shared.ids import new_id

from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

STUDENT = UUID("00000000-0000-0000-0000-0000000000b9")


async def test_swapped_key_lists_unreadable_and_delete_works(
    db_session: AsyncSession,
) -> None:
    """ADM-CRYPT-SQL-20: list shows a stub, other readers skip it, delete works."""
    store = MemoryEssayKeyStore()
    repo = SqlEssayRepository(db_session, AesGcmEssayCipher(store))
    essay = Essay(id=new_id(), student_id=STUDENT, title="Old", body="sealed once")
    await repo.add(essay)
    await repo.add_idea(EssayIdea(id=new_id(), student_id=STUDENT, body="idea"))
    answers = SqlShortAnswerRepository(db_session, AesGcmEssayCipher(store))
    await answers.put(ShortAnswer(STUDENT, "why", "short text", 2))
    await db_session.flush()
    db_session.expunge_all()

    store.keys[STUDENT] = EssayKey(STUDENT, os.urandom(KEY_BYTES))
    cipher = AesGcmEssayCipher(store)
    repo = SqlEssayRepository(db_session, cipher)

    with capture_logs() as logs:
        listed = await repo.list_for(STUDENT, include_unreadable=True)
        assert await repo.list_for(STUDENT) == []
        assert await repo.ideas_for(STUDENT) == []
        assert (
            await SqlShortAnswerRepository(db_session, cipher).for_student(STUDENT)
            == []
        )
    assert len(listed) == 1 and listed[0].unreadable
    assert (listed[0].id, listed[0].title, listed[0].body) == (essay.id, "", "")
    assert any(e["event"] == "essay_row_unreadable" for e in logs)

    assert await repo.owner_of(essay.id) == STUDENT
    await repo.delete(essay.id)
    await db_session.flush()
    assert await repo.list_for(STUDENT, include_unreadable=True) == []


async def test_missing_key_is_unreadable_too(db_session: AsyncSession) -> None:
    """ADM-CRYPT-SQL-21: a destroyed key skips the row instead of a 503."""
    store = MemoryEssayKeyStore()
    repo = SqlEssayRepository(db_session, AesGcmEssayCipher(store))
    await repo.add(Essay(id=new_id(), student_id=STUDENT, body="x"))
    await db_session.flush()
    db_session.expunge_all()
    await store.destroy(STUDENT)
    repo = SqlEssayRepository(db_session, AesGcmEssayCipher(store))
    assert await repo.list_for(STUDENT) == []
    assert [
        e.unreadable for e in await repo.list_for(STUDENT, include_unreadable=True)
    ] == [True]
