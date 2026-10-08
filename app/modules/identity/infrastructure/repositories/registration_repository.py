"""id.users queries and writes of registration, reclaim, EMIS password and deletion."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.modules.identity.application.register_models import (
    AccountSnapshot,
    NewStudentAccount,
)
from app.modules.identity.infrastructure.orm.user import User
from app.shared.actor import Role
from app.shared.base_error import ConflictError
from app.shared.contracts.identity import UserStatus

from sqlalchemy import ColumnElement, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

_DEFAULT_LOCALE = "ru"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_snapshot(row: User) -> AccountSnapshot:
    emis_status: Literal["active", "needs_reauth"] | None = (
        "needs_reauth"
        if row.emis_status == "needs_reauth"
        else "active" if row.emis_status == "active" else None
    )
    return AccountSnapshot(
        id=row.id,
        login=row.login,
        status=UserStatus(row.status),
        roles=frozenset(Role(r) for r in row.roles),
        first_name=row.first_name,
        last_name=row.last_name,
        middle_name=row.middle_name,
        recovery_email=row.recovery_email,
        password_hash=row.password_hash,
        otp_enabled=row.otp_enabled,
        locale=str((row.preferences or {}).get("locale", _DEFAULT_LOCALE)),
        emis_student_id=row.emis_student_id,
        emis_vault_ref=row.emis_vault_ref,
        emis_status=emis_status,
    )


def _registration_values(account: NewStudentAccount) -> dict[str, object]:
    return {
        "login": account.login,
        "password_hash": account.password_hash,
        "first_name": account.first_name,
        "last_name": account.last_name,
        "middle_name": account.middle_name,
        "roles": [Role.STUDENT.value],
        "recovery_email": account.recovery_email,
        "recovery_email_verified_at": account.verified_at,
        "status": UserStatus.ACTIVE.value,
        "emis_student_id": account.emis_student_id,
        "emis_vault_ref": account.emis_vault_ref,
        "emis_status": "active",
        "activation_token_hash": None,
        "activation_expires_at": None,
        "activation_purpose": None,
    }


class RegistrationRepository:
    """Bound to the unit of work's session; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the session of the current transaction."""
        self._session = session

    async def _one(self, condition: ColumnElement[bool]) -> AccountSnapshot | None:
        statement = (
            select(User).where(condition).execution_options(populate_existing=True)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return None if row is None else _to_snapshot(row)

    async def get(self, user_id: UUID) -> AccountSnapshot | None:
        """Load one account."""
        return await self._one(User.id == user_id)

    async def get_by_emis_student_id(
        self, emis_student_id: int
    ) -> AccountSnapshot | None:
        """Load the account linked to an EMIS profile."""
        return await self._one(User.emis_student_id == emis_student_id)

    async def lock_logins(self) -> None:
        """Take an advisory lock so logins are handed out one registration at a time."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('id.users.login'))")
        )

    async def taken_logins(self, prefix: str) -> set[str]:
        """Return the lowercase logins that start with ``prefix``."""
        pattern = f"{_escape_like(prefix.lower())}%"
        statement = select(func.lower(User.login)).where(
            func.lower(User.login).like(pattern, escape="\\")
        )
        return {value for value in (await self._session.scalars(statement)) if value}

    async def email_in_use(self, email: str, *, except_user_id: UUID | None) -> bool:
        """Return True if another account has this recovery email."""
        statement = select(User.id).where(
            func.lower(User.recovery_email) == email.strip().lower()
        )
        if except_user_id is not None:
            statement = statement.where(User.id != except_user_id)
        return (await self._session.scalars(statement.limit(1))).first() is not None

    async def release_deleted_emis_link(self, emis_student_id: int) -> None:
        """Free the EMIS profile of a deleted account for a new registration."""
        await self._session.execute(
            update(User)
            .where(
                User.emis_student_id == emis_student_id,
                User.status == UserStatus.DELETED.value,
            )
            .values(emis_student_id=None)
        )

    async def save_student(self, account: NewStudentAccount) -> None:
        """Insert a new active student, or activate the imported (unregistered) one."""
        values = _registration_values(account)
        values["preferences"] = {"locale": account.locale}
        if not account.activates_import:
            self._session.add(User(id=account.user_id, **values))
            await self._session.flush()
            return
        result = await self._session.execute(
            update(User)
            .where(
                User.id == account.user_id,
                User.status == UserStatus.UNREGISTERED.value,
            )
            .values(**values)
            .returning(User.id)
        )
        if result.scalar_one_or_none() is None:
            raise ConflictError(support_details="imported account is not unregistered")

    async def set_credentials(
        self,
        user_id: UUID,
        *,
        password_hash: str,
        recovery_email: str,
        now: datetime,
    ) -> None:
        """Replace the password and the verified recovery email."""
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                password_hash=password_hash,
                recovery_email=recovery_email,
                recovery_email_verified_at=now,
            )
        )

    async def set_emis_status(
        self, user_id: UUID, status: Literal["active", "needs_reauth"]
    ) -> None:
        """Set ``emis_status``."""
        await self._session.execute(
            update(User).where(User.id == user_id).values(emis_status=status)
        )

    async def mark_deleted(self, user_id: UUID, now: datetime) -> None:
        """Set status ``deleted`` and ``deleted_at``."""
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(status=UserStatus.DELETED.value, deleted_at=now)
        )

    async def clear_emis_secret(self, user_id: UUID) -> None:
        """Forget the Vault reference once the secret is destroyed."""
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(emis_vault_ref=None, emis_status=None)
        )
