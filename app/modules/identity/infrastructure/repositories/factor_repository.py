"""SQLAlchemy repository of TOTP state and passkeys."""

from uuid import UUID

from app.modules.identity.domain.factors import Passkey, UserFactors
from app.modules.identity.infrastructure.orm.factors import PasskeyRow, UserFactorsRow

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def _factors(row: UserFactorsRow) -> UserFactors:
    return UserFactors(
        user_id=row.user_id,
        totp_secret_enc=row.totp_secret_enc,
        totp_enabled_at=row.totp_enabled_at,
        totp_last_step=row.totp_last_step,
        recovery_code_hashes=list(row.recovery_code_hashes or []),
        password_login_disabled=row.password_login_disabled,
    )


def _passkey(row: PasskeyRow) -> Passkey:
    return Passkey(
        id=row.id,
        user_id=row.user_id,
        credential_id=row.credential_id,
        public_key=row.public_key,
        sign_count=row.sign_count,
        name=row.name,
        created_at=row.created_at,
        transports=list(row.transports or []),
        backed_up=row.backed_up,
        last_used_at=row.last_used_at,
    )


class SqlFactorRepository:
    """FactorRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def get(self, user_id: UUID) -> UserFactors | None:
        """The factors row of the user."""
        row = await self._session.get(UserFactorsRow, user_id)
        return _factors(row) if row else None

    async def save(self, factors: UserFactors) -> None:
        """Insert or replace the row."""
        row = await self._session.get(UserFactorsRow, factors.user_id)
        if row is None:
            row = UserFactorsRow(user_id=factors.user_id)
            self._session.add(row)
        row.totp_secret_enc = factors.totp_secret_enc
        row.totp_enabled_at = factors.totp_enabled_at
        row.totp_last_step = factors.totp_last_step
        row.recovery_code_hashes = list(factors.recovery_code_hashes)
        row.password_login_disabled = factors.password_login_disabled
        await self._session.flush()

    async def list_passkeys(self, user_id: UUID) -> list[Passkey]:
        """Oldest first."""
        rows = await self._session.scalars(
            select(PasskeyRow)
            .where(PasskeyRow.user_id == user_id)
            .order_by(PasskeyRow.created_at, PasskeyRow.id)
        )
        return [_passkey(row) for row in rows]

    async def get_passkey(self, passkey_id: UUID) -> Passkey | None:
        """One passkey by id."""
        row = await self._session.get(PasskeyRow, passkey_id)
        return _passkey(row) if row else None

    async def get_passkey_by_credential(self, credential_id: bytes) -> Passkey | None:
        """One passkey by credential id."""
        row = await self._session.scalar(
            select(PasskeyRow).where(PasskeyRow.credential_id == credential_id)
        )
        return _passkey(row) if row else None

    async def add_passkey(self, passkey: Passkey) -> None:
        """Insert."""
        self._session.add(
            PasskeyRow(
                id=passkey.id,
                user_id=passkey.user_id,
                credential_id=passkey.credential_id,
                public_key=passkey.public_key,
                sign_count=passkey.sign_count,
                transports=list(passkey.transports),
                backed_up=passkey.backed_up,
                name=passkey.name,
                created_at=passkey.created_at,
                last_used_at=passkey.last_used_at,
            )
        )
        await self._session.flush()

    async def save_passkey(self, passkey: Passkey) -> None:
        """Update the mutable fields."""
        row = await self._session.get(PasskeyRow, passkey.id)
        if row is None:
            raise LookupError(str(passkey.id))
        row.name = passkey.name
        row.sign_count = passkey.sign_count
        row.backed_up = passkey.backed_up
        row.last_used_at = passkey.last_used_at
        await self._session.flush()

    async def delete_passkey(self, passkey_id: UUID) -> None:
        """Remove."""
        await self._session.execute(
            delete(PasskeyRow).where(PasskeyRow.id == passkey_id)
        )
