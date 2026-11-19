"""Stored essay reviews on PostgreSQL: one row per input, sealed result."""

from uuid import UUID

from app.bootstrap import common  # noqa: F401  (registers every model)
from app.modules.admission.domain.essay_reviews import StoredReview
from app.modules.admission.domain.essays import Essay
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.modules.admission.infrastructure.essay_reviews_repository import (
    SqlEssayReviewRepository,
)
from app.modules.admission.infrastructure.essays_repository import SqlEssayRepository
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STUDENT = UUID("00000000-0000-0000-0000-0000000000d1")
OTHER = UUID("00000000-0000-0000-0000-0000000000d2")


def _review(
    essay_id: UUID,
    student: UUID = STUDENT,
    *,
    kind: str = "base",
    institution_id: UUID | None = None,
    digest: str = "d" * 64,
    score: int = 7,
) -> StoredReview:
    return StoredReview(
        id=new_id(),
        essay_id=essay_id,
        student_id=student,
        kind=kind,  # type: ignore[arg-type]
        institution_id=institution_id,
        input_digest=digest,
        payload={"score": score, "note": "vivid opening"},
        model="m",
        prompt_ref="p@1",
        created_at=NOW,
    )


async def _setup(
    s: AsyncSession, student: UUID = STUDENT
) -> tuple[SqlEssayReviewRepository, UUID, AesGcmEssayCipher]:
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    essay = Essay(id=new_id(), student_id=student, body="text")
    await SqlEssayRepository(s, cipher).add(essay)
    await s.flush()
    return SqlEssayReviewRepository(s, cipher), essay.id, cipher


async def _uni(s: AsyncSession, name: str) -> UUID:
    row = InstitutionRow(id=new_id(), name=name, country="GB")
    s.add(row)
    await s.flush()
    return row.id


async def test_round_trip_and_sealed_result(db_session: AsyncSession) -> None:
    """ADM-REV-SQL-01: a saved review is read back and stored as ciphertext."""
    repo, essay_id, _ = await _setup(db_session)
    review = _review(essay_id)
    await repo.save(review)
    raw = await db_session.scalar(
        text("SELECT result FROM admission.essay_reviews WHERE id = :i"),
        {"i": review.id},
    )
    assert isinstance(raw, bytes) and raw[0] == 0x01 and b"vivid" not in raw
    db_session.expunge_all()
    found = await repo.find(essay_id, "base", None, review.input_digest)
    assert found is not None and found.payload == review.payload
    assert (await repo.latest(essay_id, "base", None)) is not None


async def test_one_base_review_per_digest_cache_hit_and_refresh(
    db_session: AsyncSession,
) -> None:
    """ADM-REV-SQL-02: same digest is one row; saving again replaces the result."""
    repo, essay_id, _ = await _setup(db_session)
    await repo.save(_review(essay_id, score=5))
    await repo.save(_review(essay_id, score=9))
    rows = await repo.list_for_essay(essay_id)
    assert len(rows) == 1 and rows[0].payload["score"] == 9
    hit = await repo.find(essay_id, "base", None, "d" * 64)
    assert hit is not None and hit.payload["score"] == 9
    assert await repo.find(essay_id, "base", None, "e" * 64) is None
    await repo.save(_review(essay_id, digest="e" * 64))
    assert len(await repo.list_for_essay(essay_id)) == 2


async def test_one_uni_review_per_institution(db_session: AsyncSession) -> None:
    """ADM-REV-SQL-03: each institution has its own review beside the base one."""
    repo, essay_id, _ = await _setup(db_session)
    a, b = await _uni(db_session, "Uni A"), await _uni(db_session, "Uni B")
    await repo.save(_review(essay_id))
    await repo.save(_review(essay_id, kind="uni", institution_id=a, score=1))
    await repo.save(_review(essay_id, kind="uni", institution_id=b, score=2))
    await repo.save(_review(essay_id, kind="uni", institution_id=a, score=3))
    assert len(await repo.list_for_essay(essay_id)) == 3
    la = await repo.latest(essay_id, "uni", a)
    lb = await repo.latest(essay_id, "uni", b)
    assert la is not None and la.payload["score"] == 3
    assert lb is not None and lb.payload["score"] == 2
    base = await repo.latest(essay_id, "base", None)
    assert base is not None and base.institution_id is None


async def test_reviews_are_scoped_to_their_essay_and_owner(
    db_session: AsyncSession,
) -> None:
    """ADM-REV-SQL-04: another essay sees nothing; a shredded owner key fails closed."""
    repo, mine, cipher = await _setup(db_session)
    _, theirs, _ = await _setup(db_session, OTHER)
    await repo.save(_review(mine))
    assert await repo.list_for_essay(theirs) == []
    assert await repo.find(theirs, "base", None, "d" * 64) is None
    await cipher.forget(STUDENT)
    db_session.expunge_all()
    with pytest.raises(ValueError):
        await repo.list_for_essay(mine)
