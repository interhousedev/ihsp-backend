"""Essay review links on PostgreSQL: hashed tokens, sealed text, cascades."""

from datetime import timedelta
from uuid import UUID

from app.bootstrap import common  # noqa: F401  (registers every model)
from app.modules.admission.domain.essay_invites import (
    EssayInvite,
    Feedback,
    new_token,
    token_hash,
)
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.modules.admission.infrastructure.essay_invites_repository import (
    SqlEssayFeedbackRepository,
    SqlEssayInviteRepository,
)
from app.modules.admission.infrastructure.orm.profile import EssayRow
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STUDENT = UUID("00000000-0000-0000-0000-0000000000c1")
SECRET = "my mother read this first"


async def _essay(s: AsyncSession) -> UUID:
    essay_id = new_id()
    s.add(
        EssayRow(
            id=essay_id,
            student_id=STUDENT,
            title=b"t",
            body=b"b",
            notes=b"n",
            plan=b"p",
            links=[],
        )
    )
    await s.flush()
    return essay_id


async def _seed(
    s: AsyncSession, cipher: AesGcmEssayCipher | None = None
) -> tuple[UUID, str, Feedback]:
    cipher = cipher or AesGcmEssayCipher(MemoryEssayKeyStore())
    invites = SqlEssayInviteRepository(s, cipher)
    feedback = SqlEssayFeedbackRepository(s, cipher)
    essay_id = await _essay(s)
    token = new_token()
    invite = EssayInvite(
        id=new_id(),
        essay_id=essay_id,
        student_id=STUDENT,
        token_hash=token_hash(token),
        label="Mum",
        audience="parent",
        can_comment=True,
        expires_at=NOW + timedelta(days=30),
        created_at=NOW,
    )
    await invites.add(invite)
    root = Feedback(
        id=new_id(),
        essay_id=essay_id,
        student_id=STUDENT,
        invite_id=invite.id,
        parent_id=None,
        quote="read this",
        anchor_start=0,
        anchor_end=9,
        body=SECRET,
        author_name="Mum",
        audience="parent",
        created_at=NOW,
    )
    await feedback.add(root)
    reply = Feedback(
        id=new_id(),
        essay_id=essay_id,
        student_id=STUDENT,
        invite_id=None,
        parent_id=root.id,
        quote=None,
        anchor_start=None,
        anchor_end=None,
        body="thanks",
        author_name="",
        audience=None,
        created_at=NOW + timedelta(minutes=1),
    )
    await feedback.add(reply)
    await s.flush()
    return essay_id, token, root


async def _count(s: AsyncSession, table: str, essay_id: UUID) -> int:
    sql = text(
        f"SELECT count(*) FROM admission.{table} WHERE essay_id = :e"
    )  # noqa: S608
    return int((await s.execute(sql, {"e": essay_id})).scalar_one())


async def test_token_hash_only_and_text_sealed(db_session: AsyncSession) -> None:
    """ADM-INV-20: the table holds the token hash and no plain comment text."""
    essay_id, token, _ = await _seed(db_session)
    row = (
        await db_session.execute(
            text(
                "SELECT token_hash, label FROM admission.essay_invites "
                "WHERE essay_id = :e"
            ),
            {"e": essay_id},
        )
    ).one()
    assert row.token_hash == token_hash(token) and token not in row.token_hash
    assert b"Mum" not in bytes(row.label)
    bodies = (
        await db_session.execute(
            text(
                "SELECT body, author_name FROM admission.essay_feedback "
                "WHERE essay_id = :e"
            ),
            {"e": essay_id},
        )
    ).all()
    assert all(SECRET.encode() not in bytes(b.body) for b in bodies)
    assert all(b"Mum" not in bytes(b.author_name) for b in bodies)


async def test_round_trip_and_lookup_by_hash(db_session: AsyncSession) -> None:
    """ADM-INV-21: a link is found by its hash and opens the sealed text again."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    _, token, root = await _seed(db_session, cipher)
    invites = SqlEssayInviteRepository(db_session, cipher)
    found = await invites.by_token_hash(token_hash(token))
    assert found is not None and found.label == "Mum"
    assert await invites.count_active(found.essay_id, NOW) == 1
    await invites.revoke(found.id, NOW)
    assert await invites.count_active(found.essay_id, NOW) == 0
    items = await SqlEssayFeedbackRepository(db_session, cipher).list_for_invite(
        found.id
    )
    assert [i.body for i in items] == [root.body]


async def test_delete_cascades(db_session: AsyncSession) -> None:
    """ADM-INV-22: deleting a comment drops replies; deleting the essay drops all."""
    essay_id, _, root = await _seed(db_session)
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    await SqlEssayFeedbackRepository(db_session, cipher).delete(root.id)
    await db_session.flush()
    assert await _count(db_session, "essay_feedback", essay_id) == 0
    await db_session.execute(
        text("DELETE FROM admission.essays WHERE id = :e"), {"e": essay_id}
    )
    assert await _count(db_session, "essay_invites", essay_id) == 0


def test_ttl_bounds() -> None:
    """ADM-INV-SQL-23: a link lives 1..90 days."""
    from app.modules.admission.domain.essay_invites import check_ttl
    from app.shared.base_error import ValidationFailedError

    import pytest

    assert check_ttl(1) == timedelta(days=1) and check_ttl(90) == timedelta(days=90)
    for days in (0, 91, -1):
        with pytest.raises(ValidationFailedError):
            check_ttl(days)


async def test_revoke_and_comments_scoped(db_session: AsyncSession) -> None:
    """ADM-INV-SQL-24: revoke deactivates the link; comments list per invite."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    essay_id, token, root = await _seed(db_session, cipher)
    invites = SqlEssayInviteRepository(db_session, cipher)
    feedback = SqlEssayFeedbackRepository(db_session, cipher)
    invite = await invites.by_token_hash(token_hash(token))
    assert invite is not None and invite.is_active(NOW)
    assert [f.id for f in await feedback.list_for_invite(invite.id)] == [root.id]
    assert len(await feedback.list_for_essay(essay_id)) == 2
    await invites.revoke(invite.id, NOW)
    after = await invites.by_token_hash(token_hash(token))
    assert after is not None and not after.is_active(NOW + timedelta(minutes=1))
    assert not invite.is_active(NOW + timedelta(days=31))
