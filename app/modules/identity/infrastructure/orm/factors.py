"""ORM models of id.user_factors and id.passkeys."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class UserFactorsRow(TimestampMixin, Base):
    """TOTP secret (Vault Transit ciphertext), recovery code hashes, password switch."""

    __tablename__ = "user_factors"
    __table_args__ = ({"schema": "id"},)

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE"), primary_key=True
    )
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    recovery_code_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    password_login_disabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )


class PasskeyRow(IdMixin, TimestampMixin, Base):
    """A WebAuthn credential of a user."""

    __tablename__ = "passkeys"
    __table_args__ = (
        UniqueConstraint("credential_id", name="uq_passkeys_credential_id"),
        Index("ix_passkeys_user_id", "user_id"),
        {"schema": "id"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE")
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    transports: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    backed_up: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    name: Mapped[str] = mapped_column(String(100))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
