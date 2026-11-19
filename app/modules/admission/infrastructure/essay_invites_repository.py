"""SQL repositories of essay review links and feedback, sealed per student."""

from datetime import datetime
from typing import cast
from uuid import UUID

from app.modules.admission.domain.essay_invites import Audience, EssayInvite, Feedback
from app.modules.admission.infrastructure.orm.essay_invites import (
    EssayFeedbackRow,
    EssayInviteRow,
)
from app.modules.admission.ports.essay_crypto import EssayCipher

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def _seal(
    cipher: EssayCipher, owner: UUID, record: UUID, column: str, text: str | None
) -> bytes | None:
    """Seal a nullable column; None stays NULL."""
    if text is None:
        return None
    return await cipher.seal(owner, record, column, text)


async def _open(
    cipher: EssayCipher, owner: UUID, record: UUID, column: str, blob: bytes | None
) -> str | None:
    """Open a nullable column; NULL stays None."""
    if blob is None:
        return None
    return await cipher.open(owner, record, column, blob)


class SqlEssayInviteRepository:
    """Review links; the label is sealed with the essay owner's key."""

    def __init__(self, session: AsyncSession, cipher: EssayCipher) -> None:
        """Keep the session and the cipher."""
        self._s = session
        self._c = cipher

    async def _invite(self, row: EssayInviteRow) -> EssayInvite:
        return EssayInvite(
            id=row.id,
            essay_id=row.essay_id,
            student_id=row.student_id,
            token_hash=row.token_hash,
            label=await _open(self._c, row.student_id, row.id, "label", row.label),
            audience=cast(Audience, row.audience),
            can_comment=row.can_comment,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            created_at=row.created_at,
            last_opened_at=row.last_opened_at,
        )

    async def add(self, invite: EssayInvite) -> EssayInvite:
        """Store a new link."""
        row = EssayInviteRow(
            id=invite.id,
            essay_id=invite.essay_id,
            student_id=invite.student_id,
            token_hash=invite.token_hash,
            label=await _seal(
                self._c, invite.student_id, invite.id, "label", invite.label
            ),
            audience=invite.audience,
            can_comment=invite.can_comment,
            expires_at=invite.expires_at,
            created_at=invite.created_at,
        )
        self._s.add(row)
        await self._s.flush()
        return invite

    async def get(self, invite_id: UUID) -> EssayInvite | None:
        """Return a link by id."""
        row = await self._s.get(EssayInviteRow, invite_id)
        return None if row is None else await self._invite(row)

    async def by_token_hash(self, digest: str) -> EssayInvite | None:
        """Return the link of a token hash, whatever its state."""
        row = await self._s.scalar(
            select(EssayInviteRow).where(EssayInviteRow.token_hash == digest)
        )
        return None if row is None else await self._invite(row)

    async def list_for_essay(self, essay_id: UUID) -> list[EssayInvite]:
        """Return every link of an essay, newest first."""
        rows = await self._s.scalars(
            select(EssayInviteRow)
            .where(EssayInviteRow.essay_id == essay_id)
            .order_by(EssayInviteRow.created_at.desc(), EssayInviteRow.id.desc())
        )
        return [await self._invite(r) for r in rows]

    async def count_active(self, essay_id: UUID, now: datetime) -> int:
        """Count the links of an essay that are neither revoked nor expired."""
        found = await self._s.scalar(
            select(func.count())
            .select_from(EssayInviteRow)
            .where(
                EssayInviteRow.essay_id == essay_id,
                EssayInviteRow.revoked_at.is_(None),
                EssayInviteRow.expires_at > now,
            )
        )
        return int(found or 0)

    async def revoke(self, invite_id: UUID, now: datetime) -> None:
        """Stamp a link as revoked (idempotent)."""
        await self._s.execute(
            update(EssayInviteRow)
            .where(EssayInviteRow.id == invite_id, EssayInviteRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def touch(self, invite_id: UUID, now: datetime) -> None:
        """Record when a link was last opened."""
        await self._s.execute(
            update(EssayInviteRow)
            .where(EssayInviteRow.id == invite_id)
            .values(last_opened_at=now)
        )


class SqlEssayFeedbackRepository:
    """Feedback; quote, body and author name are sealed with the owner's key."""

    def __init__(self, session: AsyncSession, cipher: EssayCipher) -> None:
        """Keep the session and the cipher."""
        self._s = session
        self._c = cipher

    async def _item(self, row: EssayFeedbackRow) -> Feedback:
        owner, rid = row.student_id, row.id
        return Feedback(
            id=rid,
            essay_id=row.essay_id,
            student_id=owner,
            invite_id=row.invite_id,
            parent_id=row.parent_id,
            quote=await _open(self._c, owner, rid, "quote", row.quote),
            anchor_start=row.anchor_start,
            anchor_end=row.anchor_end,
            body=await self._c.open(owner, rid, "body", row.body),
            author_name=await self._c.open(owner, rid, "author_name", row.author_name),
            audience=cast(Audience | None, row.audience),
            created_at=row.created_at,
            resolved_at=row.resolved_at,
        )

    async def add(self, item: Feedback) -> Feedback:
        """Store a comment."""
        owner, rid = item.student_id, item.id
        row = EssayFeedbackRow(
            id=rid,
            essay_id=item.essay_id,
            student_id=owner,
            invite_id=item.invite_id,
            parent_id=item.parent_id,
            quote=await _seal(self._c, owner, rid, "quote", item.quote),
            anchor_start=item.anchor_start,
            anchor_end=item.anchor_end,
            body=await self._c.seal(owner, rid, "body", item.body),
            author_name=await self._c.seal(owner, rid, "author_name", item.author_name),
            audience=item.audience,
            created_at=item.created_at,
        )
        self._s.add(row)
        await self._s.flush()
        return item

    async def get(self, feedback_id: UUID) -> Feedback | None:
        """Return a comment by id."""
        row = await self._s.get(EssayFeedbackRow, feedback_id)
        return None if row is None else await self._item(row)

    async def _list(self, *where: object) -> list[Feedback]:
        rows = await self._s.scalars(
            select(EssayFeedbackRow)
            .where(*where)  # type: ignore[arg-type]
            .order_by(EssayFeedbackRow.created_at, EssayFeedbackRow.id)
        )
        return [await self._item(r) for r in rows]

    async def list_for_essay(self, essay_id: UUID) -> list[Feedback]:
        """Return every comment of an essay, oldest first."""
        return await self._list(EssayFeedbackRow.essay_id == essay_id)

    async def list_for_invite(self, invite_id: UUID) -> list[Feedback]:
        """Return the comments left through one link, oldest first."""
        return await self._list(EssayFeedbackRow.invite_id == invite_id)

    async def set_resolved(self, feedback_id: UUID, at: datetime | None) -> None:
        """Mark a comment resolved at `at`, or open again with None."""
        await self._s.execute(
            update(EssayFeedbackRow)
            .where(EssayFeedbackRow.id == feedback_id)
            .values(resolved_at=at)
        )

    async def delete(self, feedback_id: UUID) -> None:
        """Delete a comment with its replies (the foreign key cascades)."""
        await self._s.execute(
            delete(EssayFeedbackRow).where(EssayFeedbackRow.id == feedback_id)
        )
