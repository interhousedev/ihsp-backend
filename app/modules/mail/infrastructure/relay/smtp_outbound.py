"""People-to-people outbound email over aiosmtplib (Mailpit in development)."""

from email.message import EmailMessage

from app.modules.mail.domain.errors import OutboundMailFailedError
from app.settings import MailOutboundSettings

import aiosmtplib

TIMEOUT_SECONDS = 30.0
IMPLICIT_TLS_PORT = 465


class AiosmtplibOutbound:
    """Implements OutboundSmtp with the ``MAIL__OUTBOUND__*`` settings."""

    def __init__(self, settings: MailOutboundSettings) -> None:
        """Store the SMTP settings."""
        self._settings = settings

    async def send(self, message: EmailMessage) -> None:
        """Send the message; SMTP and network errors become OutboundMailFailedError."""
        settings = self._settings
        password = settings.password.get_secret_value() if settings.password else None
        try:
            await aiosmtplib.send(
                message,
                hostname=settings.host,
                port=settings.port,
                username=settings.user,
                password=password,
                start_tls=settings.starttls and settings.port != IMPLICIT_TLS_PORT,
                use_tls=settings.port == IMPLICIT_TLS_PORT,
                timeout=TIMEOUT_SECONDS,
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            raise OutboundMailFailedError(
                support_details=str(exc) or type(exc).__name__
            ) from exc
