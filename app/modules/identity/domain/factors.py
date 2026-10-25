"""Sign-in factors of a user: the authenticator app (TOTP) and passkeys."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class UserFactors:
    """TOTP state, recovery codes and the password sign-in switch of one user."""

    user_id: UUID
    totp_secret_enc: str | None = None
    """The base32 secret, encrypted with the Vault Transit key; never plaintext."""
    totp_enabled_at: datetime | None = None
    totp_last_step: int | None = None
    """The 30-second step of the last accepted code: a code is never accepted twice."""
    recovery_code_hashes: list[str] = field(default_factory=list)
    password_login_disabled: bool = False

    @property
    def totp_enabled(self) -> bool:
        """True once the authenticator app is confirmed."""
        return self.totp_enabled_at is not None and self.totp_secret_enc is not None

    def clear_totp(self) -> None:
        """Forget the secret and the recovery codes."""
        self.totp_secret_enc = None
        self.totp_enabled_at = None
        self.totp_last_step = None
        self.recovery_code_hashes = []


@dataclass(slots=True)
class Passkey:
    """A WebAuthn credential registered by a user."""

    id: UUID
    user_id: UUID
    credential_id: bytes
    public_key: bytes
    sign_count: int
    name: str
    created_at: datetime
    transports: list[str] = field(default_factory=list)
    backed_up: bool = False
    last_used_at: datetime | None = None
