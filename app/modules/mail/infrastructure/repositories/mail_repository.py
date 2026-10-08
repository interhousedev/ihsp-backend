"""SQLAlchemy repository of mailbox messages (mail.mail_messages)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.mail_meta import MailMeta
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.modules.mail.infrastructure.orm.mail_message import (
    MailMessage as MailMessageRow,
)

from sqlalchemy import DateTime, cast, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

_PARSED = "parsed_at"
_COUNTED = "suspension_counted"
_PURGED = "purged"


def _to_entity(row: MailMessageRow) -> MailMessage:
    return MailMessage(
        id=row.id,
        user_id=row.user_id,
        direction=MailDirection(row.direction),
        message_id=row.message_id,
        from_address=row.from_address,
        occurred_at=row.occurred_at,
        status=MailStatus(row.status),
        to=list(row.to),
        cc=list(row.cc),
        subject=row.subject,
        snippet=row.snippet,
        in_reply_to=row.in_reply_to,
        references=list(row.references),
        raw_file_id=row.raw_file_id,
        attachment_file_ids=list(row.attachment_file_ids),
        spam_score=row.spam_score,
        meta=MailMeta.model_validate(row.meta or {}),
    )


def _values(mail: MailMessage) -> dict[str, Any]:
    return {
        "user_id": mail.user_id,
        "direction": mail.direction.value,
        "message_id": mail.message_id,
        "in_reply_to": mail.in_reply_to,
        "references": mail.references,
        "from_address": mail.from_address,
        "to": mail.to,
        "cc": mail.cc,
        "subject": mail.subject,
        "snippet": mail.snippet,
        "raw_file_id": mail.raw_file_id,
        "attachment_file_ids": mail.attachment_file_ids,
        "spam_score": mail.spam_score,
        "status": mail.status.value,
        "occurred_at": mail.occurred_at,
        "meta": mail.meta.to_json(),
    }


def _has_key(name: str) -> Any:
    return func.jsonb_exists(MailMessageRow.meta, name)


class SqlMailRepository:
    """MailRepository over one AsyncSession owned by the unit of work."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self._session = session

    async def add(self, mail: MailMessage) -> bool:
        """Insert the mail; False when (user, direction, Message-ID) exists."""
        stmt = (
            pg_insert(MailMessageRow)
            .values(id=mail.id, **_values(mail))
            .on_conflict_do_nothing(
                index_elements=["user_id", "direction", "message_id"]
            )
            .returning(MailMessageRow.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def get(self, mail_id: UUID) -> MailMessage | None:
        """Return the mail or None."""
        row = await self._session.get(MailMessageRow, mail_id, populate_existing=True)
        return None if row is None else _to_entity(row)

    async def get_owned(self, user_id: UUID, mail_id: UUID) -> MailMessage | None:
        """Return the mail only if it is in this user's mailbox."""
        mail = await self.get(mail_id)
        return mail if mail is not None and mail.user_id == user_id else None

    async def save(self, mail: MailMessage) -> None:
        """Write every column of an existing row."""
        await self._session.execute(
            update(MailMessageRow)
            .where(MailMessageRow.id == mail.id)
            .values(**_values(mail))
        )

    async def inbound_exists(self, user_id: UUID, message_id: str) -> bool:
        """True if the mailbox already has a received mail with this Message-ID."""
        stmt = select(MailMessageRow.id).where(
            MailMessageRow.user_id == user_id,
            MailMessageRow.direction == MailDirection.IN.value,
            MailMessageRow.message_id == message_id,
        )
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def recent(
        self, user_id: UUID, *, limit: int, before: datetime | None
    ) -> list[MailMessage]:
        """List non-spam mails, newest first, strictly older than ``before``."""
        stmt = select(MailMessageRow).where(
            MailMessageRow.user_id == user_id,
            MailMessageRow.status != MailStatus.SPAM.value,
        )
        if before is not None:
            stmt = stmt.where(MailMessageRow.occurred_at < before)
        stmt = stmt.order_by(
            MailMessageRow.occurred_at.desc(), MailMessageRow.id.desc()
        ).limit(limit)
        return [_to_entity(row) for row in await self._session.scalars(stmt)]

    async def find_outbound(
        self, user_id: UUID, message_ids: Sequence[str]
    ) -> MailMessage | None:
        """Return the user's sent mail whose Message-ID is among the given ones."""
        if not message_ids:
            return None
        stmt = (
            select(MailMessageRow)
            .where(
                MailMessageRow.user_id == user_id,
                MailMessageRow.direction == MailDirection.OUT.value,
                MailMessageRow.message_id.in_(list(message_ids)),
            )
            .order_by(MailMessageRow.occurred_at.desc())
            .limit(1)
        )
        row = (await self._session.scalars(stmt)).first()
        return None if row is None else _to_entity(row)

    async def unparsed_inbound(self, older_than: datetime, limit: int) -> list[UUID]:
        """Ids of received or spam mails not parsed yet and older than the moment."""
        stmt = (
            select(MailMessageRow.id)
            .where(
                MailMessageRow.direction == MailDirection.IN.value,
                MailMessageRow.status.in_(
                    (MailStatus.RECEIVED.value, MailStatus.SPAM.value)
                ),
                MailMessageRow.occurred_at < older_than,
                ~_has_key(_PARSED),
            )
            .order_by(MailMessageRow.occurred_at)
            .limit(limit)
        )
        return list(await self._session.scalars(stmt))

    async def stale_queued(self, older_than: datetime, limit: int) -> list[UUID]:
        """Ids of outbound mails still queued and older than the moment."""
        stmt = (
            select(MailMessageRow.id)
            .where(
                MailMessageRow.direction == MailDirection.OUT.value,
                MailMessageRow.status == MailStatus.QUEUED.value,
                MailMessageRow.occurred_at < older_than,
            )
            .order_by(MailMessageRow.occurred_at)
            .limit(limit)
        )
        return list(await self._session.scalars(stmt))

    def _bounces_since(self, since: datetime) -> Any:
        bounced_at = cast(
            MailMessageRow.meta.op("->>")("bounced_at"), DateTime(timezone=True)
        )
        return (
            MailMessageRow.direction == MailDirection.OUT.value,
            MailMessageRow.status == MailStatus.BOUNCED.value,
            bounced_at >= since,
            ~_has_key(_COUNTED),
        )

    async def users_with_bounces(
        self, since: datetime, minimum: int
    ) -> dict[UUID, int]:
        """Uncounted bounces per user since the moment, for users with >= minimum."""
        count = func.count()
        stmt = (
            select(MailMessageRow.user_id, count)
            .where(*self._bounces_since(since))
            .group_by(MailMessageRow.user_id)
            .having(count >= minimum)
        )
        rows = (await self._session.execute(stmt)).all()
        return {user_id: int(total) for user_id, total in rows}

    async def mark_bounces_counted(self, user_id: UUID, since: datetime) -> None:
        """Flag the user's bounces since the moment as used for a suspension."""
        stmt = select(MailMessageRow).where(
            MailMessageRow.user_id == user_id, *self._bounces_since(since)
        )
        for row in await self._session.scalars(stmt):
            row.meta = {**(row.meta or {}), _COUNTED: True}
        await self._session.flush()

    async def delete_spam_before(self, cutoff: datetime) -> int:
        """Delete spam rows received before the cutoff; return how many."""
        stmt = (
            delete(MailMessageRow)
            .where(
                MailMessageRow.status == MailStatus.SPAM.value,
                MailMessageRow.occurred_at < cutoff,
            )
            .returning(MailMessageRow.id)
        )
        return len((await self._session.execute(stmt)).all())

    async def flag_purged_before(self, cutoff: datetime) -> int:
        """Set ``meta.purged`` on rows received before the cutoff; return how many."""
        flag = literal({_PURGED: True}, type_=JSONB)
        stmt = (
            update(MailMessageRow)
            .where(MailMessageRow.occurred_at < cutoff, ~_has_key(_PURGED))
            .values(meta=MailMessageRow.meta.op("||")(flag))
            .returning(MailMessageRow.id)
        )
        return len((await self._session.execute(stmt)).all())
