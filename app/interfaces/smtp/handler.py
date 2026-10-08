"""aiosmtpd handler: accept mail only for existing mailboxes (MAIL-9)."""

from typing import Any

from app.modules.mail.application.receive_inbound import ReceiveInbound
from app.modules.mail.application.resolve_mailbox import ResolveMailbox

import structlog

log = structlog.get_logger(__name__)

NO_SUCH_MAILBOX = "550 5.1.1 No such mailbox"
TOO_MANY_RECIPIENTS = "452 4.5.3 Too many recipients"
TEMPORARY_FAILURE = "451 4.3.0 Temporary local problem, try again later"
ACCEPTED = "250 OK queued"


def _as_bytes(content: object) -> bytes:
    if isinstance(content, bytes):
        return content
    return (
        content.encode("utf-8", "surrogateescape") if isinstance(content, str) else b""
    )


def _peer_ip(peer: object) -> str:
    if isinstance(peer, tuple | list) and peer:
        return str(peer[0])
    return "" if peer is None else str(peer)


class InboundHandler:
    """Checks recipients in RCPT and hands the whole message to ReceiveInbound."""

    def __init__(
        self,
        *,
        resolve_mailbox: ResolveMailbox,
        receive_inbound: ReceiveInbound,
        max_recipients: int,
    ) -> None:
        """Store the use cases and the recipient limit."""
        self._resolve_mailbox = resolve_mailbox
        self._receive_inbound = receive_inbound
        self._max_recipients = max_recipients

    async def handle_RCPT(  # noqa: N802
        self,
        server: Any,
        session: Any,
        envelope: Any,
        address: str,
        rcpt_options: list[str],
    ) -> str:
        """Accept ``<login>@<mail domain>`` of an active student, else 550 5.1.1."""
        if len(envelope.rcpt_tos) >= self._max_recipients:
            return TOO_MANY_RECIPIENTS
        try:
            user_id = await self._resolve_mailbox.execute(address)
        except Exception:  # a SMTP hook must answer, never crash
            log.exception("rcpt_lookup_failed")
            return TEMPORARY_FAILURE
        if user_id is None:
            return NO_SUCH_MAILBOX
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(  # noqa: N802
        self, server: Any, session: Any, envelope: Any
    ) -> str:
        """Check, store and queue the message, then answer 250."""
        raw = _as_bytes(
            envelope.original_content
            if envelope.original_content is not None
            else envelope.content
        )
        try:
            await self._receive_inbound.execute(
                raw,
                peer_ip=_peer_ip(session.peer),
                helo=session.host_name or "",
                mail_from=envelope.mail_from or "",
                recipients=list(envelope.rcpt_tos),
            )
        except Exception:  # tell the sender to retry later
            log.exception("inbound_mail_failed")
            return TEMPORARY_FAILURE
        return ACCEPTED
