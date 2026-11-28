"""Wallet passes of the student card (Apple Wallet and Google Wallet)."""

from typing import Protocol

from app.modules.identity.domain.student_card import WalletPass


class StudentCardWallet(Protocol):
    """Builds wallet passes; a wallet without its settings is disabled."""

    @property
    def apple_enabled(self) -> bool:
        """Whether an Apple Wallet pass can be signed."""
        ...

    @property
    def google_enabled(self) -> bool:
        """Whether a Google Wallet save link can be signed."""
        ...

    def apple_pass(self, data: WalletPass) -> bytes:
        """Return a signed `.pkpass` archive."""
        ...

    def google_save_url(self, data: WalletPass) -> str:
        """Return the "Add to Google Wallet" link with a signed JWT."""
        ...
