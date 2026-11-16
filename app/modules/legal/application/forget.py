"""A user's acceptances of one app scope are deleted (erasure from that app)."""

from uuid import UUID

from app.modules.legal.application.queries import RequireConsent
from app.modules.legal.ports.unit_of_work import UowFactory


class ForgetScope:
    """Delete the acceptances of one scope so the app asks for consent again."""

    def __init__(
        self, *, uow_factory: UowFactory, require_consent: RequireConsent
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._require_consent = require_consent

    async def execute(self, user_id: UUID, app_scope: str) -> int:
        """Delete the user's acceptances of ``app_scope``; return how many."""
        async with self._uow_factory() as uow:
            removed = await uow.legal.delete_acceptances(user_id, app_scope)
            await uow.commit()
        self._require_consent.forget(user_id)
        return removed
