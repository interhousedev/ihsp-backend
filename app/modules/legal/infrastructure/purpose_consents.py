"""SQL store of the admission purpose consents (implements admission's port)."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.admission.ports.consent import PURPOSE_VERSIONS, PurposeGrant
from app.modules.legal.infrastructure.orm.tables import PurposeConsentRow
from app.shared.ids import new_id

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _grant(row: PurposeConsentRow) -> PurposeGrant:
    return PurposeGrant(
        row.purpose, row.method, row.given_at, row.withdrawn_at, row.version
    )


class SqlPurposeConsents:
    """One short transaction per call, on the shared sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def granted(self, user_ids: Sequence[UUID]) -> dict[UUID, frozenset[str]]:
        """Return the purposes in force per user; users without any are absent."""
        if not user_ids:
            return {}
        async with self._sm() as s:
            rows = await s.execute(
                select(
                    PurposeConsentRow.user_id,
                    PurposeConsentRow.purpose,
                    PurposeConsentRow.version,
                ).where(
                    PurposeConsentRow.user_id.in_(list(user_ids)),
                    PurposeConsentRow.withdrawn_at.is_(None),
                )
            )
        out: dict[UUID, set[str]] = {}
        for user_id, purpose, version in rows.tuples():
            if version != PURPOSE_VERSIONS.get(purpose, 1):
                continue
            out.setdefault(user_id, set()).add(purpose)
        return {u: frozenset(p) for u, p in out.items()}

    async def grants_of(self, user_id: UUID) -> list[PurposeGrant]:
        """Return the stored answer of every purpose of the user."""
        async with self._sm() as s:
            rows = await s.scalars(
                select(PurposeConsentRow).where(PurposeConsentRow.user_id == user_id)
            )
            return [_grant(r) for r in rows]

    async def grant(
        self, user_id: UUID, purpose: str, *, now: dt.datetime, method: str = "app"
    ) -> PurposeGrant:
        """Record the consent; a purpose already in force is returned unchanged."""
        version = PURPOSE_VERSIONS[purpose]
        async with self._sm() as s, s.begin():
            row = await s.scalar(
                select(PurposeConsentRow)
                .where(
                    PurposeConsentRow.user_id == user_id,
                    PurposeConsentRow.purpose == purpose,
                )
                .with_for_update()
            )
            if row is None:
                row = PurposeConsentRow(
                    id=new_id(),
                    user_id=user_id,
                    purpose=purpose,
                    method=method,
                    given_at=now,
                    version=version,
                )
                s.add(row)
            elif row.withdrawn_at is not None or row.version != version:
                row.method, row.given_at, row.withdrawn_at = method, now, None
                row.version = version
            return _grant(row)

    async def withdraw(self, user_id: UUID, purpose: str, *, now: dt.datetime) -> bool:
        """Withdraw the consent; return whether one was in force."""
        async with self._sm() as s, s.begin():
            row = await s.scalar(
                select(PurposeConsentRow)
                .where(
                    PurposeConsentRow.user_id == user_id,
                    PurposeConsentRow.purpose == purpose,
                    PurposeConsentRow.withdrawn_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                return False
            row.withdrawn_at = now
            return True

    async def forget(self, user_id: UUID) -> None:
        """Delete every stored answer of the user."""
        async with self._sm() as s, s.begin():
            await s.execute(
                delete(PurposeConsentRow).where(PurposeConsentRow.user_id == user_id)
            )
