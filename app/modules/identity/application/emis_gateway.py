"""The ID module's gateway to EMIS: stored token, one re-login (ID-7)."""

from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

from app.modules.identity.application.register_errors import emis_errors
from app.modules.identity.application.register_models import (
    AccountSnapshot,
    CredentialStoreError,
    EmisAuthError,
    EmisSecret,
)
from app.modules.identity.application.register_ports import (
    CredentialStore,
    EmisApi,
    UnitOfWorkFactory,
)
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisClassHour,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisTimetableItem,
    EmisUnavailable,
)
from app.shared.contracts.identity import UserStatus

import structlog

log = structlog.get_logger(__name__)
T = TypeVar("T")


class EmisGatewayImpl:
    """Implements ``EmisSource`` in-process; only the identity process builds it."""

    def __init__(
        self,
        *,
        emis: EmisApi,
        store: CredentialStore,
        uow_factory: UnitOfWorkFactory,
    ) -> None:
        """Store the EMIS client, Vault and the account unit of work."""
        self._emis = emis
        self._store = store
        self._uow_factory = uow_factory

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Return the student's EMIS profile."""
        return await self._call(user_id, self._emis.profile)

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Return the student's curriculum."""
        return await self._call(user_id, self._emis.curriculum)

    async def ratings(
        self, user_id: UUID, emis_subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return the marks of one subject in one semester."""

        async def fetch(token: str) -> EmisSubjectRatings:
            return await self._emis.ratings(token, emis_subject_id, semester)

        return await self._call(user_id, fetch)

    async def class_hours(self, user_id: UUID) -> list[EmisClassHour]:
        """Return the lyceum's bells (any linked student's token will do)."""
        return await self._call(user_id, self._emis.class_hours)

    async def timetable(self, user_id: UUID) -> list[EmisTimetableItem]:
        """Return the weekly timetable of the student's group."""
        return await self._call(user_id, self._emis.timetable)

    # - - - Token handling - - -

    async def _call(self, user_id: UUID, fetch: Callable[[str], Awaitable[T]]) -> T:
        """Run an EMIS call with the stored token; re-login once on HTTP 401."""
        account = await self._linked_account(user_id)
        ref = account.emis_vault_ref
        if ref is None:  # _linked_account rules this out
            raise EmisAuthFailed(support_details="no EMIS link")
        with emis_errors():
            secret = await self._store.read(ref)
            try:
                return await fetch(secret.access_token)
            except EmisAuthError:
                pass
        token = await self._relogin(user_id, ref, secret)
        with emis_errors():
            try:
                return await fetch(token)
            except EmisAuthError as exc:
                # A token we just got was refused: EMIS misbehaves, not the password.
                raise EmisUnavailable(support_details="fresh token rejected") from exc

    async def _linked_account(self, user_id: UUID) -> AccountSnapshot:
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(user_id)
        if (
            account is None
            or account.status is not UserStatus.ACTIVE
            or account.emis_vault_ref is None
            or account.emis_status == "needs_reauth"
        ):
            raise EmisAuthFailed(support_details="no usable EMIS link")
        return account

    async def _relogin(self, user_id: UUID, ref: UUID, secret: EmisSecret) -> str:
        """Log in with the stored password; EMIS refusing it means ``needs_reauth``."""
        with emis_errors():
            password = await self._store.decrypt(secret.password_enc)
            try:
                token = await self._emis.login(secret.login, password)
            except EmisAuthError:
                await self._mark_needs_reauth(user_id)
                raise
        try:
            await self._store.update_token(ref, token)
        except CredentialStoreError:
            log.warning("could not store the fresh EMIS token", user_id=str(user_id))
        return token

    async def _mark_needs_reauth(self, user_id: UUID) -> None:
        async with self._uow_factory() as uow:
            await uow.accounts.set_emis_status(user_id, "needs_reauth")
            await uow.commit()
