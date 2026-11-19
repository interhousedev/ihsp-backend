"""Essay text on PostgreSQL is ciphertext; repository and export see plaintext."""

from uuid import UUID

from app.bootstrap import common  # noqa: F401  (registers every model)
from app.modules.admission.domain.essays import Essay, EssayIdea, PlanSection
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.modules.admission.infrastructure.essays_repository import SqlEssayRepository
from app.modules.admission.infrastructure.staff_repositories import (
    SqlPrivacyRepository,
)
from app.shared.ids import new_id

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STUDENT = UUID("00000000-0000-0000-0000-0000000000a7")
BODY = "My grandmother's kitchen in Chorsu"


async def test_essay_body_is_sealed_at_rest(db_session: AsyncSession) -> None:
    """ADM-CRYPT-17: the stored body is bytes without the text; reads open it."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    repo = SqlEssayRepository(db_session, cipher)
    essay = Essay(id=new_id(), student_id=STUDENT, title="Kitchen", body=BODY)
    await repo.add(essay)
    await db_session.flush()

    raw = await db_session.scalar(
        text("SELECT body FROM admission.essays WHERE id = :id"), {"id": essay.id}
    )
    assert isinstance(raw, bytes) and BODY.encode() not in raw
    db_session.expunge_all()
    loaded = await repo.get(essay.id)
    assert loaded is not None and (loaded.title, loaded.body) == ("Kitchen", BODY)

    export = await SqlPrivacyRepository(db_session, cipher).export(STUDENT)
    assert [r["body"] for r in export["essays"]] == [BODY]


async def test_shredded_key_exports_nulls(db_session: AsyncSession) -> None:
    """ADM-CRYPT-18: after forget the export keeps the row but not the text."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    essay = Essay(id=new_id(), student_id=STUDENT, body=BODY)
    await SqlEssayRepository(db_session, cipher).add(essay)
    await db_session.flush()
    await cipher.forget(STUDENT)

    export = await SqlPrivacyRepository(db_session, cipher).export(STUDENT)
    assert [r["body"] for r in export["essays"]] == [None]


async def _raw(s: AsyncSession, table: str, column: str, row_id: UUID) -> bytes:
    raw = await s.scalar(
        text(f"SELECT {column} FROM admission.{table} WHERE id = :id"),  # noqa: S608
        {"id": row_id},
    )
    assert isinstance(raw, bytes)
    return raw


async def test_every_essay_column_is_versioned_ciphertext(
    db_session: AsyncSession,
) -> None:
    """ADM-CRYPT-SQL-01: title, body, notes, plan and idea tags are 0x01 blobs."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    repo = SqlEssayRepository(db_session, cipher)
    essay = Essay(
        id=new_id(),
        student_id=STUDENT,
        title="Kitchen",
        body=BODY,
        notes="secret notes",
        plan=(PlanSection(heading="Opening", note="smell of bread"),),
    )
    await repo.add(essay)
    idea = EssayIdea(
        id=new_id(), student_id=STUDENT, body="idea", tags=("family", "food")
    )
    await repo.add_idea(idea)
    await db_session.flush()

    plain = {
        "title": b"Kitchen",
        "body": BODY.encode(),
        "notes": b"secret notes",
        "plan": b"smell of bread",
    }
    for column, needle in plain.items():
        raw = await _raw(db_session, "essays", column, essay.id)
        assert raw[0] == 0x01 and needle not in raw, column
    tags = await _raw(db_session, "essay_ideas", "tags", idea.id)
    assert tags[0] == 0x01 and b"family" not in tags

    db_session.expunge_all()
    loaded = await repo.get(essay.id)
    assert loaded is not None
    assert loaded.title == "Kitchen" and loaded.body == BODY
    assert loaded.notes == "secret notes"
    assert loaded.plan == essay.plan
    got = await repo.get_idea(idea.id)
    assert got is not None and got.tags == ("family", "food")


async def test_shredded_key_fails_closed_on_read(db_session: AsyncSession) -> None:
    """ADM-CRYPT-SQL-02: with the key destroyed, reads raise, no plaintext."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    repo = SqlEssayRepository(db_session, cipher)
    essay = Essay(id=new_id(), student_id=STUDENT, body=BODY)
    idea = EssayIdea(id=new_id(), student_id=STUDENT, body="x", tags=("t",))
    await repo.add(essay)
    await repo.add_idea(idea)
    await db_session.flush()
    await cipher.forget(STUDENT)
    db_session.expunge_all()

    with pytest.raises(ValueError):
        await repo.get(essay.id)
    with pytest.raises(ValueError):
        await repo.get_idea(idea.id)
