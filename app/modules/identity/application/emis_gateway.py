"""The ID module's gateway to EMIS: stored token, one re-login (ID-7)."""

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar
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
    EmisClass,
    EmisClassHour,
    EmisCurriculum,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisUnavailable,
)
from app.shared.contracts.identity import UserStatus

import structlog

log = structlog.get_logger(__name__)
T = TypeVar("T")


class OfflineTokens(Protocol):
    """Fake EMIS only: the token of a student, found from the EMIS student id."""

    def token_for(self, emis_student_id: int) -> str | None:
        """Return the token, or None for an id the fake EMIS does not know."""
        ...


def _usable(account: AccountSnapshot, stored_secret: bool) -> bool:
    """Active, not flagged for reauth, and linked by Vault reference or EMIS id."""
    link = account.emis_vault_ref if stored_secret else account.emis_student_id
    return (
        account.status is UserStatus.ACTIVE
        and account.emis_status != "needs_reauth"
        and link is not None
    )


class EmisGatewayImpl:
    """Implements ``EmisSource`` in-process; only the identity process builds it.

    With ``fake_tokens`` (EMIS mode fake) no Vault secret is needed: the token comes
    from the student's EMIS id. The real client always goes through the stored secret.
    """

    def __init__(
        self,
        *,
        emis: EmisApi,
        store: CredentialStore,
        uow_factory: UnitOfWorkFactory,
        fake_tokens: OfflineTokens | None = None,
    ) -> None:
        """Store the EMIS client, Vault, the account unit of work and fake tokens."""
        self._emis = emis
        self._store = store
        self._uow_factory = uow_factory
        self._fake_tokens = fake_tokens

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Return the student's EMIS profile."""
        return await self._call(user_id, self._emis.profile)

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Return the student's curriculum."""
        return await self._call(user_id, self._emis.curriculum)

    async def curriculum(self, user_id: UUID) -> EmisCurriculum:
        """Return the whole curriculum of the student: semesters, hours, exams."""
        return await self._call(user_id, self._emis.curriculum_detail)

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

    async def timetable(
        self, user_id: UUID, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the student's classes on the dates begin..end."""

        async def fetch(token: str) -> list[EmisClass]:
            return await self._emis.timetable(token, begin, end)

        return await self._call(user_id, fetch)

    # - - - Token handling - - -

    async def _call(self, user_id: UUID, fetch: Callable[[str], Awaitable[T]]) -> T:
        """Run an EMIS call with the stored token; re-login once on HTTP 401."""
        if self._fake_tokens is not None:
            return await self._call_fake(user_id, self._fake_tokens, fetch)
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

    async def _call_fake(
        self,
        user_id: UUID,
        tokens: OfflineTokens,
        fetch: Callable[[str], Awaitable[T]],
    ) -> T:
        """Fake EMIS: the token follows from the EMIS id; Vault is not read."""
        account = await self._linked_account(user_id, stored_secret=False)
        if account.emis_student_id is None:  # _linked_account rules this out
            raise EmisAuthFailed(support_details="no EMIS link")
        token = tokens.token_for(account.emis_student_id)
        if token is None:
            raise EmisAuthFailed(support_details="unknown EMIS student")
        with emis_errors():
            return await fetch(token)

    async def _linked_account(
        self, user_id: UUID, *, stored_secret: bool = True
    ) -> AccountSnapshot:
        """The account, if EMIS can be called for it (``stored_secret``: Vault link)."""
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(user_id)
        if account is None or not _usable(account, stored_secret):
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
