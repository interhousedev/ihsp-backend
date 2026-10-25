"""Renderers the bot registers in the notification renderer registry.

The notification dispatcher (module notify) renders a notification per
recipient with these functions: lesson_prompt, mail, telegram_linked,
otp_reset_requested and feedback_response. The contract objects are resolved
when a notification is rendered, because the container is still being
assembled when the renderers are registered.
"""

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.interfaces.bot.prompt_state import parse_prompt_state
from app.interfaces.bot.screens.lesson_prompt import build_lesson_prompt
from app.interfaces.bot.screens.linked_notice import (
    build_linked_elsewhere,
    build_linked_here,
)
from app.interfaces.bot.screens.mail_message import (
    TELEGRAM_FILE_LIMIT,
    build_mail_message,
    parse_mail_view,
)
from app.interfaces.bot.screens.otp_reset_notice import build_otp_reset_notice
from app.interfaces.bot.services import BotServices, services_from_container
from app.interfaces.bot.utilities.html import escape
from app.shared.actor import Role
from app.shared.base_error import ForbiddenError, NotFoundError
from app.shared.contracts.notify import RenderContext, RenderedMessage, Renderer
from app.shared.notifications import NotificationType


class RendererRegistry(Protocol):
    """The registry of notification renderers (owned by the notify module)."""

    def register(self, type_: NotificationType, renderer: Renderer, /) -> None:
        """Register the renderer of one notification type."""
        ...


def _uuid(payload: dict[str, Any], key: str) -> UUID:
    return UUID(str(payload[key]))


def _moment(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def make_lesson_prompt_renderer(container: Any) -> Renderer:
    """Render the end-of-lesson prompt for the teacher (BOT-16)."""

    async def render(
        payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        services = services_from_container(container)
        try:
            raw = await services.classwork.prompt_state(
                _uuid(payload, "lesson_id"), ctx.user.id
            )
        except (ForbiddenError, NotFoundError):
            return None  # reassigned or gone: nothing to ask
        state = parse_prompt_state(raw)
        done = state.attendance_submitted and bool(state.homework_text)
        if state.expired or done or state.lesson.status == "cancelled":
            return None
        return build_lesson_prompt(
            state,
            services.i18n.get_context(ctx.locale),
            now=services.clock.now(),
            urls=services.urls,
        )

    return render


async def _load_attachments(
    view_attachments: Any, services: BotServices
) -> tuple[tuple[tuple[str, bytes], ...], list[str]]:
    """Read attachments up to Telegram's 50 MB; larger ones are only named."""
    documents: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for attachment in view_attachments:
        if attachment.byte_size > TELEGRAM_FILE_LIMIT:
            skipped.append(attachment.name)
            continue
        documents.append(
            (attachment.name, await services.files.read_bytes(attachment.id))
        )
    return tuple(documents), skipped


def make_mail_renderer(container: Any) -> Renderer:
    """Render an incoming email with its attachments as documents (MAIL-2)."""

    async def render(
        payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        services = services_from_container(container)
        try:
            raw = await services.mail.view(ctx.user.id, _uuid(payload, "mail_id"))
        except NotFoundError:
            return None
        view = parse_mail_view(raw)
        documents, skipped = await _load_attachments(view.attachments, services)
        return build_mail_message(
            view,
            services.i18n.get_context(ctx.locale),
            documents=documents,
            skipped_names=skipped,
        )

    return render


def make_telegram_linked_renderer(container: Any) -> Renderer:
    """Greet the linked account; tell the user's other channels with Not me."""

    async def render(
        payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        services = services_from_container(container)
        i18n = services.i18n.get_context(ctx.locale)
        if int(payload["telegram_user_id"]) == ctx.telegram_user_id:
            return build_linked_here(ctx.user, i18n, services.urls)
        return build_linked_elsewhere(
            payload.get("telegram_username"), i18n, services.urls
        )

    return render


def make_otp_reset_renderer(container: Any) -> Renderer:
    """Tell the user an OTP delivery reset was requested, with Cancel."""

    async def render(
        payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        services = services_from_container(container)
        return build_otp_reset_notice(
            _uuid(payload, "request_id"),
            _moment(payload["effective_at"]),
            services.i18n.get_context(ctx.locale),
        )

    return render


async def _feedback_documents(
    attachments: list[dict[str, Any]], services: BotServices
) -> tuple[tuple[tuple[str, bytes], ...], list[str]]:
    """Read the response's files up to 50 MB; larger or missing ones are named."""
    documents: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for item in attachments:
        name = str(item.get("name", ""))
        if int(item.get("size", 0)) > TELEGRAM_FILE_LIMIT:
            skipped.append(name)
            continue
        try:
            data = await services.files.read_bytes(_uuid(item, "file_id"))
        except NotFoundError:
            skipped.append(name)
            continue
        documents.append((name, data))
    return tuple(documents), skipped


def make_feedback_response_renderer(container: Any) -> Renderer:
    """Send an administrator's reply to feedback, its files as documents."""

    async def render(
        payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        services = services_from_container(container)
        i18n = services.i18n.get_context(ctx.locale)
        documents, skipped = await _feedback_documents(
            list(payload.get("attachments") or []), services
        )
        title = i18n("notify-feedback-response-title", title=payload.get("title", ""))
        lines = [f"<b>{escape(title)}</b>", escape(str(payload.get("text", "")))]
        lines += [f"📎 {escape(name)}" for name in skipped]
        staff = Role.TEACHER in ctx.user.roles and Role.STUDENT not in ctx.user.roles
        base = services.urls.staff if staff else services.urls.sp
        link = f"{base}/feedback/?id={payload.get('feedback_id', '')}"
        return RenderedMessage(
            text_html="\n".join(lines),
            buttons=[[{"text": i18n("notify-btn-open-feedback"), "web_app_url": link}]],
            documents=documents,
        )

    return render


def register_bot_renderers(registry: RendererRegistry, container: Any) -> None:
    """Register lesson_prompt, mail, telegram_linked, otp_reset, feedback, artifacts."""
    registry.register(
        NotificationType.LESSON_PROMPT, make_lesson_prompt_renderer(container)
    )
    registry.register(NotificationType.MAIL, make_mail_renderer(container))
    registry.register(
        NotificationType.TELEGRAM_LINKED, make_telegram_linked_renderer(container)
    )
    registry.register(
        NotificationType.OTP_RESET_REQUESTED, make_otp_reset_renderer(container)
    )
    registry.register(
        NotificationType.FEEDBACK_RESPONSE, make_feedback_response_renderer(container)
    )
    # Imported here: it pulls the notebooks export, which the bot tests do not need.
    from app.interfaces.bot.assistant.artifact_notice import (
        make_artifact_ready_renderer,
    )

    registry.register(
        NotificationType.NOTEBOOK_ARTIFACT_READY,
        make_artifact_ready_renderer(container),
    )
