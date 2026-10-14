"""SQLAlchemy repository of users (id.users)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.infrastructure.orm import User as UserRow
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.pagination import Page, decode_cursor, encode_cursor

from sqlalchemy import ARRAY, Text, and_, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

PURGED_NAME = "Deleted"


def _to_entity(row: UserRow) -> User:
    return User(
        id=row.id,
        first_name=row.first_name,
        last_name=row.last_name,
        middle_name=row.middle_name,
        login=row.login,
        password_hash=row.password_hash,
        password_change_required=row.password_change_required,
        roles={Role(item) for item in row.roles or []},
        recovery_email=row.recovery_email,
        recovery_email_verified_at=row.recovery_email_verified_at,
        otp_enabled=row.otp_enabled,
        otp_via_email=row.otp_via_email,
        status=UserStatus(row.status),
        auth_epoch=row.auth_epoch,
        activation_token_hash=row.activation_token_hash,
        activation_expires_at=row.activation_expires_at,
        activation_purpose=(
            ActivationPurpose(row.activation_purpose)
            if row.activation_purpose
            else None
        ),
        emis_student_id=row.emis_student_id,
        emis_teacher_id=row.emis_teacher_id,
        emis_vault_ref=row.emis_vault_ref,
        emis_status=row.emis_status,  # type: ignore[arg-type]
        mail_suspended_at=row.mail_suspended_at,
        preferences=dict(row.preferences or {}),
        last_login_at=row.last_login_at,
        otp_reset_effective_at=row.otp_reset_effective_at,
        otp_reset_request_id=row.otp_reset_request_id,
        deleted_at=row.deleted_at,
        deletion_requested_at=row.deletion_requested_at,
        photo_file_id=row.photo_file_id,
        created_at=row.created_at,
    )


def _apply(row: UserRow, user: User) -> None:
    row.first_name = user.first_name
    row.last_name = user.last_name
    row.middle_name = user.middle_name
    row.login = user.login
    row.password_hash = user.password_hash
    row.password_change_required = user.password_change_required
    row.roles = sorted(role.value for role in user.roles)
    row.recovery_email = user.recovery_email
    row.recovery_email_verified_at = user.recovery_email_verified_at
    row.otp_enabled = user.otp_enabled
    row.otp_via_email = user.otp_via_email
    row.status = user.status.value
    row.auth_epoch = user.auth_epoch
    row.activation_token_hash = user.activation_token_hash
    row.activation_expires_at = user.activation_expires_at
    row.activation_purpose = (
        user.activation_purpose.value if user.activation_purpose else None
    )
    row.emis_student_id = user.emis_student_id
    row.emis_teacher_id = user.emis_teacher_id
    row.emis_vault_ref = user.emis_vault_ref
    row.emis_status = user.emis_status
    row.mail_suspended_at = user.mail_suspended_at
    row.preferences = user.preferences
    row.last_login_at = user.last_login_at
    row.otp_reset_effective_at = user.otp_reset_effective_at
    row.otp_reset_request_id = user.otp_reset_request_id
    row.deleted_at = user.deleted_at
    row.deletion_requested_at = user.deletion_requested_at
    row.photo_file_id = user.photo_file_id


def _has_any_role(roles: Sequence[Role]) -> ColumnElement[bool]:
    """`roles && ARRAY[...]` (the generic ARRAY type has no overlap())."""
    values = literal([role.value for role in roles], type_=ARRAY(Text))
    return UserRow.roles.bool_op("&&")(values)


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _text_filter(query: str) -> ColumnElement[bool]:
    pattern = _like(query.strip())
    return or_(
        UserRow.login.ilike(pattern, escape="\\"),
        UserRow.first_name.ilike(pattern, escape="\\"),
        UserRow.last_name.ilike(pattern, escape="\\"),
        UserRow.recovery_email.ilike(pattern, escape="\\"),
    )


class SqlUserRepository:
    """UserRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        """Return the user or None."""
        row = await self._session.get(UserRow, user_id)
        return _to_entity(row) if row else None

    async def get_many(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        """Return the existing users among the ids."""
        if not user_ids:
            return {}
        rows = await self._session.scalars(
            select(UserRow).where(UserRow.id.in_(list(user_ids)))
        )
        return {row.id: _to_entity(row) for row in rows}

    async def _first(self, *conditions: ColumnElement[bool]) -> User | None:
        row = await self._session.scalar(select(UserRow).where(*conditions).limit(1))
        return _to_entity(row) if row else None

    async def get_by_login(self, login: str) -> User | None:
        """Find a user by login, case-insensitively."""
        return await self._first(func.lower(UserRow.login) == login.strip().lower())

    async def get_by_recovery_email(self, email: str) -> User | None:
        """Find a user by recovery email, case-insensitively."""
        return await self._first(
            func.lower(UserRow.recovery_email) == email.strip().lower()
        )

    async def get_by_emis_teacher_id(self, emis_teacher_id: int) -> User | None:
        """Find the teacher linked to an EMIS teacher id."""
        return await self._first(UserRow.emis_teacher_id == emis_teacher_id)

    async def list_with_roles(self, roles: Sequence[Role]) -> list[User]:
        """Return users holding any role, except deleted and deactivated ones."""
        rows = await self._session.scalars(
            select(UserRow)
            .where(
                _has_any_role(roles),
                UserRow.status.not_in(
                    [UserStatus.DELETED.value, UserStatus.DEACTIVATED.value]
                ),
            )
            .order_by(UserRow.created_at, UserRow.id)
        )
        return [_to_entity(row) for row in rows]

    async def get_by_activation_hash(self, token_hash: str) -> User | None:
        """Find the user holding an activation token hash."""
        return await self._first(UserRow.activation_token_hash == token_hash)

    async def get_by_otp_reset_request(self, request_id: UUID) -> User | None:
        """Find the user with a pending OTP reset request."""
        return await self._first(UserRow.otp_reset_request_id == request_id)

    async def add(self, user: User) -> None:
        """Insert a new user."""
        row = UserRow(id=user.id)
        _apply(row, user)
        self._session.add(row)
        await self._session.flush()

    async def save(self, user: User) -> None:
        """Write every field of an existing user."""
        row = await self._session.get(UserRow, user.id)
        if row is None:
            raise LookupError(f"user {user.id} does not exist")
        _apply(row, user)
        await self._session.flush()

    async def logins_with_prefix(self, prefix: str) -> set[str]:
        """Return the existing logins starting with the prefix (any case)."""
        pattern = _like(prefix.lower())[1:]  # drop the leading % for a prefix match
        rows = await self._session.scalars(
            select(UserRow.login).where(
                func.lower(UserRow.login).like(pattern, escape="\\")
            )
        )
        return {login.lower() for login in rows if login}

    async def email_taken(
        self, email: str, *, except_user_id: UUID | None = None
    ) -> bool:
        """True when another user's recovery email equals the email."""
        conditions = [func.lower(UserRow.recovery_email) == email.strip().lower()]
        if except_user_id is not None:
            conditions.append(UserRow.id != except_user_id)
        found = await self._session.scalar(select(UserRow.id).where(*conditions))
        return found is not None

    async def ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return ids of active users holding any of the roles."""
        rows = await self._session.scalars(
            select(UserRow.id).where(
                UserRow.status == UserStatus.ACTIVE.value,
                _has_any_role(roles),
            )
        )
        return list(rows)

    async def search(
        self,
        *,
        query: str | None,
        roles: Sequence[Role],
        status: UserStatus | None,
        cursor: str | None,
        limit: int,
    ) -> Page[User]:
        """Administration list: newest first, cursor on the id."""
        stmt = select(UserRow).order_by(UserRow.id.desc()).limit(limit + 1)
        if query and query.strip():
            stmt = stmt.where(_text_filter(query))
        if roles:
            stmt = stmt.where(_has_any_role(roles))
        if status is not None:
            stmt = stmt.where(UserRow.status == status.value)
        decoded = decode_cursor(cursor)
        if decoded:
            stmt = stmt.where(UserRow.id < UUID(decoded["id"]))
        rows = list((await self._session.scalars(stmt)).all())
        has_more = len(rows) > limit
        items = [_to_entity(row) for row in rows[:limit]]
        next_cursor = encode_cursor({"id": str(items[-1].id)}) if has_more else None
        return Page[User](items=items, next_cursor=next_cursor)

    async def search_active(
        self, query: str, *, roles: Sequence[Role], limit: int
    ) -> list[User]:
        """Active users whose name or login contains every word of the query."""
        words = [w for w in query.split() if w]
        conditions: list[ColumnElement[bool]] = [
            UserRow.status == UserStatus.ACTIVE.value
        ]
        conditions.extend(_text_filter(word) for word in words)
        if roles:
            conditions.append(_has_any_role(roles))
        rows = await self._session.scalars(
            select(UserRow)
            .where(and_(*conditions))
            .order_by(UserRow.last_name, UserRow.first_name, UserRow.id)
            .limit(limit)
        )
        return [_to_entity(row) for row in rows]

    async def due_otp_resets(self, now: datetime) -> list[User]:
        """Users whose OTP reset is due."""
        rows = await self._session.scalars(
            select(UserRow).where(
                UserRow.otp_reset_effective_at.is_not(None),
                UserRow.otp_reset_effective_at <= now,
            )
        )
        return [_to_entity(row) for row in rows]

    async def purgeable(self, deleted_before: datetime, limit: int) -> list[User]:
        """Deleted users whose personal data has not been removed yet."""
        rows = await self._session.scalars(
            select(UserRow)
            .where(
                UserRow.status == UserStatus.DELETED.value,
                UserRow.deleted_at < deleted_before,
                UserRow.first_name != PURGED_NAME,
            )
            .limit(limit)
        )
        return [_to_entity(row) for row in rows]

    async def merge_preferences(
        self, user_id: UUID, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomic `preferences || patch`; returns the merged document."""
        stmt = (
            update(UserRow)
            .where(UserRow.id == user_id)
            .values(
                preferences=func.coalesce(UserRow.preferences, literal({}, JSONB)).op(
                    "||"
                )(literal(patch, JSONB))
            )
            .returning(UserRow.preferences)
        )
        merged = (await self._session.execute(stmt)).scalar_one()
        return dict(merged)

    async def get_epoch(self, user_id: UUID) -> int | None:
        """Return the user's auth epoch, or None if the user does not exist."""
        epoch: int | None = await self._session.scalar(
            select(UserRow.auth_epoch).where(UserRow.id == user_id)
        )
        return epoch
