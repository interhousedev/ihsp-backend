"""Finish a student registration: account, Vault secret, student record, login."""

from dataclasses import dataclass
from functools import partial
from uuid import UUID

from app.modules.identity.application.register_errors import (
    EmailInUseError,
    EmailNotSetError,
    EmisAlreadyLinkedError,
    ImportMatchUnconfirmedError,
    RegistrationExpiredError,
    WeakPasswordError,
    emis_errors,
)
from app.modules.identity.application.register_models import (
    CredentialStoreError,
    NewStudentAccount,
    PendingRegistration,
)
from app.modules.identity.application.register_ports import (
    CredentialStore,
    EmisUnitOfWork,
    LoginAcceptorPort,
    PasswordHasher,
    PendingStore,
    UnitOfWorkFactory,
)
from app.modules.identity.application.register_verification import EmailVerifier
from app.modules.identity.domain.login_name import base_login, next_free
from app.modules.identity.domain.password_policy import check_password
from app.shared.clock import Clock
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RegisteredStudent:
    """The new account and where to send the browser next."""

    user_id: UUID
    login: str
    redirect_to: str | None


class CompleteRegistration:
    """Create or activate the account once the email is confirmed (ID-4, ID-5, ID-6)."""

    def __init__(
        self,
        *,
        pending: PendingStore[PendingRegistration],
        verifier: EmailVerifier,
        store: CredentialStore,
        hasher: PasswordHasher,
        uow_factory: UnitOfWorkFactory,
        enrollment: AcademicEnrollment,
        login_acceptor: LoginAcceptorPort,
        kicker: TaskKicker,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self._pending = pending
        self._verifier = verifier
        self._store = store
        self._hasher = hasher
        self._uow_factory = uow_factory
        self._enrollment = enrollment
        self._login_acceptor = login_acceptor
        self._kicker = kicker
        self._clock = clock

    async def execute(
        self,
        *,
        registration_token: str,
        password: str,
        email_code: str,
        confirm_import_match: bool,
        login_challenge: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> RegisteredStudent:
        """Validate, verify the code, write everything, then accept the login."""
        pending = await self._pending.get(registration_token)
        if pending is None:
            raise RegistrationExpiredError()
        self._check_ready(pending, password, confirm_import_match)
        await self._verifier.check(registration_token, email_code)
        user_id = pending.import_user_id or new_id()
        login = await self._register(pending, user_id, password, ip, user_agent)
        await self._pending.delete(registration_token)
        redirect_to = await self._accept_login(login_challenge, user_id, ip, user_agent)
        return RegisteredStudent(user_id=user_id, login=login, redirect_to=redirect_to)

    @staticmethod
    def _check_ready(
        pending: PendingRegistration, password: str, confirmed: bool
    ) -> None:
        errors = check_password(password)
        if errors:
            raise WeakPasswordError(params={"errors": errors})
        if pending.email is None:
            raise EmailNotSetError()
        if pending.import_needs_confirmation and not confirmed:
            raise ImportMatchUnconfirmedError()

    # - - - Writing - - -

    async def _register(
        self,
        pending: PendingRegistration,
        user_id: UUID,
        password: str,
        ip: str | None,
        user_agent: str | None,
    ) -> str:
        """Write the Vault secret, then the account; undo the secret on failure."""
        ref = new_id()
        password_hash = await self._hasher.hash(password)
        with emis_errors():
            access_token = await self._store.decrypt(pending.token_enc)
            await self._store.write(
                ref,
                login=pending.emis_login,
                password_enc=pending.password_enc,
                access_token=access_token,
            )
        try:
            return await self._create_account(
                pending, user_id, ref, password_hash, ip, user_agent
            )
        except Exception:
            await self._discard_secret(ref)
            raise

    async def _discard_secret(self, ref: UUID) -> None:
        try:
            await self._store.destroy(ref)
        except CredentialStoreError:
            log.error("orphan emis secret left in vault", vault_ref=str(ref))

    async def _create_account(
        self,
        pending: PendingRegistration,
        user_id: UUID,
        ref: UUID,
        password_hash: str,
        ip: str | None,
        user_agent: str | None,
    ) -> str:
        profile = pending.profile
        async with self._uow_factory() as uow:
            await uow.accounts.lock_logins()
            await self._ensure_free(uow, pending)
            login = await self._final_login(uow, pending)
            await uow.accounts.save_student(
                NewStudentAccount(
                    user_id=user_id,
                    activates_import=pending.import_user_id is not None,
                    login=login,
                    password_hash=password_hash,
                    first_name=profile.first_name,
                    last_name=profile.last_name,
                    middle_name=profile.middle_name,
                    recovery_email=str(pending.email),
                    verified_at=self._clock.now(),
                    emis_student_id=profile.emis_student_id,
                    emis_vault_ref=ref,
                    locale=pending.locale,
                )
            )
            student = await self._enrollment.ensure_student(
                user_id=user_id,
                group_emis_id=profile.group_emis_id,
                group_name=profile.group_name,
                current_semester=profile.current_semester,
                curriculum_id=profile.curriculum_id,
            )
            await self._enrollment.sync_subjects(
                group_id=student.group_id, subjects=pending.subjects
            )
            uow.audit(
                AuditDraft(
                    type="user.registered",
                    user_id=user_id,
                    actor_id=user_id,
                    ip=ip,
                    user_agent=user_agent,
                    metadata={
                        "emis_student_id": profile.emis_student_id,
                        "imported": pending.import_user_id is not None,
                    },
                )
            )
            uow.after_commit(
                partial(
                    self._kicker.kick,
                    "academic.backfill_student",
                    user_id=str(user_id),
                )
            )
            await uow.commit()
        return login

    @staticmethod
    async def _ensure_free(uow: EmisUnitOfWork, pending: PendingRegistration) -> None:
        """Re-check inside the transaction what start and the email step checked."""
        emis_id = pending.profile.emis_student_id
        existing = await uow.accounts.get_by_emis_student_id(emis_id)
        if existing is not None and existing.status is UserStatus.DELETED:
            await uow.accounts.release_deleted_emis_link(emis_id)
        elif existing is not None and (
            existing.id != pending.import_user_id
            or existing.status is not UserStatus.UNREGISTERED
        ):
            raise EmisAlreadyLinkedError(support_details=f"emis {emis_id}")
        if await uow.accounts.email_in_use(
            str(pending.email), except_user_id=pending.import_user_id
        ):
            raise EmailInUseError(support_details="email belongs to another user")

    @staticmethod
    async def _final_login(uow: EmisUnitOfWork, pending: PendingRegistration) -> str:
        """The login shown at the start is a preview; it is chosen again here."""
        if pending.import_user_id is not None:
            imported = await uow.accounts.get(pending.import_user_id)
            if imported is not None and imported.login:
                return imported.login
        base = base_login(pending.profile.last_name, pending.profile.first_name)
        return next_free(base, await uow.accounts.taken_logins(base))

    # - - - After the commit - - -

    async def _accept_login(
        self,
        challenge: str | None,
        user_id: UUID,
        ip: str | None,
        user_agent: str | None,
    ) -> str | None:
        """Log the new student in; failing to do so must not undo the account."""
        if challenge is None:
            return None
        try:
            return await self._login_acceptor.accept(
                challenge,
                user_id,
                amr=["pwd"],
                ip=ip,
                user_agent=user_agent,
                remember=False,
            )
        except Exception:
            log.exception("login after registration failed", user_id=str(user_id))
            return None
