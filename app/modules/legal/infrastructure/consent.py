"""The consent writer identity runs inside its registration transaction."""

from app.modules.legal.domain.models import Acceptance
from app.modules.legal.infrastructure.repositories.legal_repository import (
    SqlLegalRepository,
)
from app.shared.contracts.legal import ConsentDraft
from app.shared.ids import new_id

from sqlalchemy.ext.asyncio import AsyncSession


async def write_acceptances(session: AsyncSession, drafts: list[ConsentDraft]) -> None:
    """Insert the acceptances on the caller's session; the caller commits."""
    await SqlLegalRepository(session).add_acceptances(
        [
            Acceptance(
                id=new_id(),
                user_id=draft.user_id,
                kind=item.kind,
                version=item.version,
                accepted_at=draft.accepted_at,
                ip=draft.ip,
                user_agent=draft.user_agent,
                app_scope=item.app_scope,
            )
            for draft in drafts
            for item in draft.items
        ]
    )
