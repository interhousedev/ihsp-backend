"""Start a student registration with EMIS credentials (UF-ID-01 steps 1-5)."""

from dataclasses import dataclass

from app.modules.identity.application.register_emis_login import (
    VerifiedEmisAccount,
    VerifyEmisCredentials,
)
from app.modules.identity.application.register_errors import (
    EmisAlreadyLinkedError,
    emis_errors,
)
from app.modules.identity.application.register_models import (
    AccountSnapshot,
    PendingRegistration,
)
from app.modules.identity.application.register_ports import (
    EmisApi,
    EmisUnitOfWork,
    PendingStore,
    UnitOfWorkFactory,
)
from app.modules.identity.domain.login_name import base_login, next_free
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.contracts.emis import EmisProfile
from app.shared.contracts.identity import UserStatus


@dataclass(frozen=True, slots=True)
class ImportedMatch:
    """An imported (unregistered) record the student may be claiming."""

    first_name: str
    last_name: str
    group_name: str
    needs_confirmation: bool


@dataclass(frozen=True, slots=True)
class StartedRegistration:
    """What the registration page shows after the EMIS check."""

    registration_token: str
    profile: EmisProfile
    login: str
    imported_match: ImportedMatch | None


@dataclass(frozen=True, slots=True)
class _Match:
    account: AccountSnapshot
    needs_confirmation: bool


class StartRegistration:
    """Verify EMIS credentials and keep the pending registration in Redis."""

    def __init__(
        self,
        *,
        verify: VerifyEmisCredentials,
        emis: EmisApi,
        pending: PendingStore[PendingRegistration],
        uow_factory: UnitOfWorkFactory,
        enrollment: AcademicEnrollment,
    ) -> None:
        """Store the collaborators."""
        self._verify = verify
        self._emis = emis
        self._pending = pending
        self._uow_factory = uow_factory
        self._enrollment = enrollment

    async def execute(
        self, *, emis_login: str, emis_password: str, ip: str | None, locale: str
    ) -> StartedRegistration:
        """Check EMIS, find an import match, choose the login, store the flow."""
        verified = await self._verify.execute(
            emis_login=emis_login, emis_password=emis_password, ip=ip
        )
        with emis_errors():
            subjects = await self._emis.curriculum(verified.token)
        async with self._uow_factory() as uow:
            match = await self._find_match(uow, verified.profile)
            login = await self._choose_login(uow, verified.profile, match)
        pending = PendingRegistration(
            emis_login=verified.emis_login,
            password_enc=verified.password_enc,
            token_enc=verified.token_enc,
            profile=verified.profile,
            subjects=subjects,
            import_user_id=match.account.id if match else None,
            import_needs_confirmation=match.needs_confirmation if match else False,
            login=login,
            locale=locale,
        )
        token = await self._pending.create(pending)
        return StartedRegistration(
            registration_token=token,
            profile=verified.profile,
            login=login,
            imported_match=self._describe(match, verified),
        )

    async def _find_match(
        self, uow: EmisUnitOfWork, profile: EmisProfile
    ) -> _Match | None:
        existing = await uow.accounts.get_by_emis_student_id(profile.emis_student_id)
        if existing is not None and existing.status is not UserStatus.DELETED:
            if existing.status is not UserStatus.UNREGISTERED:
                raise EmisAlreadyLinkedError(
                    support_details=f"emis {profile.emis_student_id}"
                )
            return _Match(existing, needs_confirmation=False)
        return await self._match_by_name(uow, profile)

    async def _match_by_name(
        self, uow: EmisUnitOfWork, profile: EmisProfile
    ) -> _Match | None:
        found = await self._enrollment.find_imported_student(
            emis_student_id=profile.emis_student_id,
            first_name=profile.first_name,
            last_name=profile.last_name,
            group_name=profile.group_name,
        )
        account = None if found is None else await uow.accounts.get(found)
        if account is None or account.status is not UserStatus.UNREGISTERED:
            return None
        if account.emis_student_id not in (None, profile.emis_student_id):
            return None  # the import belongs to another EMIS profile
        return _Match(account, needs_confirmation=True)

    async def _choose_login(
        self, uow: EmisUnitOfWork, profile: EmisProfile, match: _Match | None
    ) -> str:
        if match is not None and match.account.login:
            return match.account.login
        base = base_login(profile.last_name, profile.first_name)
        return next_free(base, await uow.accounts.taken_logins(base))

    @staticmethod
    def _describe(
        match: _Match | None, verified: VerifiedEmisAccount
    ) -> ImportedMatch | None:
        if match is None:
            return None
        return ImportedMatch(
            first_name=match.account.first_name,
            last_name=match.account.last_name,
            group_name=verified.profile.group_name,
            needs_confirmation=match.needs_confirmation,
        )
