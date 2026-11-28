"""Wallet passes of the student card, built from the wallet settings."""

import logging
from dataclasses import dataclass

from app.modules.identity.domain.student_card import WalletPass
from app.modules.identity.infrastructure.wallet.apple import (
    ApplePassSigner,
    build_pkpass,
)
from app.modules.identity.infrastructure.wallet.google import GoogleWalletIssuer
from app.settings import WalletSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfiguredWallet:
    """The wallets whose settings are complete; the others stay disabled."""

    apple: ApplePassSigner | None
    google: GoogleWalletIssuer | None
    origins: list[str]

    @property
    def apple_enabled(self) -> bool:
        """Whether Apple Wallet passes can be signed."""
        return self.apple is not None

    @property
    def google_enabled(self) -> bool:
        """Whether Google Wallet links can be signed."""
        return self.google is not None

    def apple_pass(self, data: WalletPass) -> bytes:
        """Return the signed `.pkpass`."""
        if self.apple is None:
            raise RuntimeError("Apple Wallet is not configured")
        return build_pkpass(data, self.apple)

    def google_save_url(self, data: WalletPass) -> str:
        """Return the save link."""
        if self.google is None:
            raise RuntimeError("Google Wallet is not configured")
        return self.google.save_url(data, self.origins)


def build_wallet(settings: WalletSettings, origins: list[str]) -> ConfiguredWallet:
    """Load the configured wallets; a wallet whose files do not load is disabled."""
    apple: ApplePassSigner | None = None
    google: GoogleWalletIssuer | None = None
    a = settings.apple
    if a.enabled:
        try:
            apple = ApplePassSigner.from_files(
                pass_type_id=a.pass_type_id,
                team_id=a.team_id,
                cert_path=a.cert_path,
                key_path=a.key_path,
                key_password=(
                    a.key_password.get_secret_value() if a.key_password else None
                ),
                wwdr_path=a.wwdr_path,
            )
        except (OSError, ValueError):
            logger.exception("Apple Wallet disabled: its files do not load")
    g = settings.google
    if g.enabled:
        try:
            google = GoogleWalletIssuer.from_file(
                issuer_id=g.issuer_id,
                class_suffix=g.class_suffix,
                service_account_path=g.service_account_path,
            )
        except (OSError, ValueError, KeyError):
            logger.exception("Google Wallet disabled: its key file does not load")
    return ConfiguredWallet(apple=apple, google=google, origins=origins)
