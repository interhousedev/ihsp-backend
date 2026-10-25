"""Templated emails over the outbound SMTP relay (Mailpit in development)."""

import html
import re
from collections.abc import Awaitable, Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from app.modules.identity.domain.errors import EmailDeliveryError
from app.settings import SmtpOutSettings
from app.shared.i18n.core import I18nCore

import aiosmtplib
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

log = structlog.get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES = frozenset({"otp", "activation", "login_reminder", "notice"})
Transport = Callable[[EmailMessage], Awaitable[None]]


def _plain_text(markup: str) -> str:
    """Strip tags for the text/plain alternative."""
    breaks = re.sub(r"</(p|div|li|h\d)>|<br\s*/?>", "\n", markup)
    return html.unescape(re.sub(r"<[^>]+>", "", breaks)).strip()


class SmtpEmailSender:
    """EmailSender: renders a Jinja2 template with i18n and sends it."""

    def __init__(
        self,
        *,
        settings: SmtpOutSettings,
        i18n: I18nCore,
        app_name: str,
        transport: Transport | None = None,
    ) -> None:
        """Prepare the template environment; ``transport`` replaces SMTP in tests."""
        self._settings = settings
        self._i18n = i18n
        self._app_name = app_name
        self._transport = transport or self._smtp
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=select_autoescape(["html"]),
        )

    def render(
        self, to: str, template: str, params: dict[str, Any], locale: str
    ) -> EmailMessage:
        """Build the message without sending it."""
        if template not in TEMPLATES:
            raise ValueError(f"unknown email template: {template}")
        context = self._i18n.get_context(locale)
        body = self._env.get_template(f"{template}.html").render(
            t=context.get, app_name=self._app_name, locale=locale, **params
        )
        message = EmailMessage()
        message["From"] = self._settings.system_from
        message["To"] = to
        message["Subject"] = context.get(
            f"id-mail-{template.replace('_', '-')}-subject",
            app_name=self._app_name,
            **params,
        )
        message.set_content(_plain_text(body))
        message.add_alternative(body, subtype="html")
        return message

    async def send(
        self, to: str, template: str, params: dict[str, Any], locale: str
    ) -> None:
        """Render and deliver; relay problems become EmailDeliveryError."""
        message = self.render(to, template, params, locale)
        try:
            await self._transport(message)
        except (aiosmtplib.SMTPException, OSError) as exc:
            log.warning("email_send_failed", template=template, error=repr(exc))
            raise EmailDeliveryError(
                support_details=f"smtp {template}: {exc!r}"
            ) from exc

    async def _smtp(self, message: EmailMessage) -> None:
        cfg = self._settings
        await aiosmtplib.send(
            message,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password.get_secret_value() if cfg.password else None,
            start_tls=cfg.starttls,
            timeout=10,
        )
