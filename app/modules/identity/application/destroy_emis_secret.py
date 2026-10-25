"""Destroy the Vault secret of a deleted account, all versions (ID-9)."""

from uuid import UUID

from app.modules.identity.application.register_ports import (
    CredentialStore,
    UnitOfWorkFactory,
)
from app.shared.contracts.identity import UserStatus

import structlog

log = structlog.get_logger(__name__)


class DestroyEmisSecret:
    """Idempotent, so the retrying task can repeat it."""

    def __init__(
        self, *, store: CredentialStore, uow_factory: UnitOfWorkFactory
    ) -> None:
        """Store the collaborators."""
        self._store = store
        self._uow_factory = uow_factory

    async def execute(self, user_id: UUID) -> None:
        """Delete the secret, then forget its reference.

        Vault errors propagate so that the task is retried.
        """
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(user_id)
        if account is None or account.emis_vault_ref is None:
            return
        if account.status is not UserStatus.DELETED:
            log.warning(
                "refusing to destroy the secret of a live account", user=str(user_id)
            )
            return
        await self._store.destroy(account.emis_vault_ref)
        async with self._uow_factory() as uow:
            await uow.accounts.clear_emis_secret(user_id)
            await uow.commit()
