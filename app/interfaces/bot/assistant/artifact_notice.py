"""The "Studio output ready" notice with the output itself attached.

The notify module renders the notice (title, body, notebook button); in Telegram
the bot adds the output as a file (its Office format, else Markdown), so a Studio
generation approved in the bot chat comes back to that chat when the job ends.
"""

from typing import Any
from uuid import UUID

from app.interfaces.bot.screens.mail_message import TELEGRAM_FILE_LIMIT
from app.modules.notebooks.application.export.render import default_format, export_as
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notify.application.renderers.notebook_artifact_ready import (
    NotebookArtifactReadyRenderer,
)
from app.shared.contracts.notify import RenderContext, RenderedMessage, Renderer

import structlog

log = structlog.get_logger(__name__)


async def artifact_file(
    notebooks: Any, user_id: UUID, payload: dict[str, Any]
) -> tuple[str, bytes] | None:
    """The ready output as (file name, bytes); None when it cannot be exported."""
    try:
        found = await notebooks.get_artifact_content(
            user_id,
            UUID(str(payload["notebook_id"])),
            UUID(str(payload["artifact_id"])),
        )
    except (KeyError, ValueError):
        return None
    if found is None:
        return None
    kind = ArtifactKind(found["kind"])
    fmt = default_format(kind)
    if fmt is None:
        return None
    try:
        document = export_as(kind, found["title"], found["content"], fmt)
    except ValueError:
        log.info("bot.artifact_notice.export_failed", kind=kind.value)
        return None
    if len(document.data) > TELEGRAM_FILE_LIMIT:
        return None
    return document.name, document.data


def make_artifact_ready_renderer(container: Any) -> Renderer:
    """The notify module's notice plus the output as a document."""
    notice = NotebookArtifactReadyRenderer(container.i18n, container.settings.urls)

    async def render(
        payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        rendered = await notice(payload, ctx)
        notebooks = getattr(getattr(container, "notebooks", None), "public", None)
        if rendered is None or notebooks is None:
            return rendered
        attached = await artifact_file(notebooks, ctx.user.id, payload)
        if attached is None:
            return rendered
        return RenderedMessage(
            text_html=rendered.text_html,
            buttons=rendered.buttons,
            documents=(*rendered.documents, attached),
        )

    return render
