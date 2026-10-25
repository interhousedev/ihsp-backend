"""Security notices by email; a failing relay never breaks the action itself."""

from typing import Any

from app.modules.identity.domain.errors import EmailDeliveryError
from app.modules.identity.ports.email_sender import EmailSender

import structlog

log = structlog.get_logger(__name__)


async def send_notice(
    email: EmailSender,
    to: str | None,
    locale: str,
    text_key: str,
    text_params: dict[str, Any] | None = None,
    link: str | None = None,
) -> None:
    """Send the `notice` template; log and continue when the relay fails."""
    if not to:
        return
    params = {"text_key": text_key, "text_params": text_params or {}, "link": link}
    try:
        await email.send(to, "notice", params, locale)
    except EmailDeliveryError:
        log.warning("notice_email_failed", text_key=text_key)
