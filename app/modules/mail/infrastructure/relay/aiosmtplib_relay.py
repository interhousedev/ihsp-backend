"""Outbound relay over aiosmtplib (Mailpit in development, a provider in production)."""

from collections.abc import Sequence

from app.modules.mail.ports.outbound_relay import (
    RelayPermanentError,
    RelayResult,
    RelayTemporaryError,
)
from app.settings import SmtpOutSettings

import aiosmtplib

TIMEOUT_SECONDS = 30.0
IMPLICIT_TLS_PORT = 465
PERMANENT_FROM = 500


class AiosmtplibRelay:
    """Implements OutboundRelay with the ``SMTP_OUT__*`` settings."""

    def __init__(self, settings: SmtpOutSettings) -> None:
        """Store the relay settings."""
        self._settings = settings

    async def send(
        self, *, sender: str, recipients: Sequence[str], raw: bytes
    ) -> RelayResult:
        """Send the raw message; 4xx and network errors are temporary, 5xx permanent."""
        settings = self._settings
        password = settings.password.get_secret_value() if settings.password else None
        try:
            refused, _ = await aiosmtplib.send(
                raw,
                sender=sender,
                recipients=list(recipients),
                hostname=settings.host,
                port=settings.port,
                username=settings.username,
                password=password,
                start_tls=settings.starttls and settings.port != IMPLICIT_TLS_PORT,
                use_tls=settings.port == IMPLICIT_TLS_PORT,
                local_hostname=settings.mail_domain,
                timeout=TIMEOUT_SECONDS,
            )
        except aiosmtplib.SMTPRecipientsRefused as exc:
            codes = [item.code for item in exc.recipients]
            raise _classify(max(codes, default=0), str(exc)) from exc
        except aiosmtplib.SMTPAuthenticationError as exc:
            # A wrong password is our configuration problem: keep the mail queued.
            raise RelayTemporaryError(str(exc)) from exc
        except aiosmtplib.SMTPResponseException as exc:
            raise _classify(exc.code, str(exc)) from exc
        except (aiosmtplib.SMTPException, OSError) as exc:
            raise RelayTemporaryError(str(exc) or type(exc).__name__) from exc
        return RelayResult(refused=tuple(sorted(refused)))


def _classify(code: int, message: str) -> RelayPermanentError | RelayTemporaryError:
    if code >= PERMANENT_FROM:
        return RelayPermanentError(message)
    return RelayTemporaryError(message)
