"""The inbound SMTP server (``python -m app mail``): aiosmtpd without a controller."""

import asyncio
import ssl

from app.bootstrap.container import Container
from app.interfaces.smtp.handler import InboundHandler
from app.settings import SmtpInSettings

import structlog
from aiosmtpd.smtp import SMTP

log = structlog.get_logger(__name__)

IDENT = "ihsp-mx"
TIMEOUT_SECONDS = 300


def build_tls_context(settings: SmtpInSettings) -> ssl.SSLContext | None:
    """Return a server TLS context when a certificate and key are configured."""
    if not (settings.tls_cert_path and settings.tls_key_path):
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(settings.tls_cert_path, settings.tls_key_path)
    return context


async def start_smtp_server(
    handler: InboundHandler,
    settings: SmtpInSettings,
    *,
    hostname: str,
    port: int | None = None,
    host: str | None = None,
) -> asyncio.Server:
    """Start listening inside the running loop (UnthreadedController cannot).

    STARTTLS is offered, not required: senders without TLS are still accepted.
    """
    tls_context = build_tls_context(settings)
    loop = asyncio.get_running_loop()
    return await loop.create_server(
        lambda: SMTP(
            handler,
            hostname=hostname,
            data_size_limit=settings.max_bytes,
            enable_SMTPUTF8=True,
            tls_context=tls_context,
            require_starttls=False,
            ident=IDENT,
            timeout=TIMEOUT_SECONDS,
        ),
        host=host or settings.host,
        port=settings.port if port is None else port,
    )


def build_handler(container: Container) -> InboundHandler:
    """Create the handler from the mail services of the container."""
    mail = container.mail
    return InboundHandler(
        resolve_mailbox=mail.resolve_mailbox,
        receive_inbound=mail.receive_inbound,
        max_recipients=mail.config.max_inbound_recipients,
    )


async def run_mail_server(container: Container) -> None:
    """Serve until cancelled; called by ``app.bootstrap.mail``."""
    settings = container.settings.smtp_in
    server = await start_smtp_server(
        build_handler(container),
        settings,
        hostname=container.settings.smtp_out.mail_domain,
    )
    log.info("smtp_server_started", host=settings.host, port=settings.port)
    async with server:
        await server.serve_forever()
