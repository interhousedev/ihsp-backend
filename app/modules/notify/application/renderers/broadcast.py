"""Broadcast message: bold title, formatted text, media as documents (ADM-11)."""

from typing import Any
from uuid import UUID

from app.modules.notify.application.format import esc
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.i18n.core import I18nCore

import structlog

log = structlog.get_logger(__name__)


class BroadcastRenderer:
    """Renders the title and HTML text stored in the notification payload."""

    def __init__(self, i18n: I18nCore, files: FilesApi) -> None:
        """Store translations and the files API."""
        self.i18n = i18n
        self.files = files

    async def __call__(
        self, payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        """Render the broadcast; unreadable media files are skipped and logged."""
        t = self.i18n.get_context(ctx.locale)
        title = esc(payload.get("title") or t("notify-broadcast-title"))
        prefix = (
            f"<i>{esc(t('notify-broadcast-preview'))}</i>\n"
            if payload.get("preview")
            else ""
        )
        text_html = f"{prefix}<b>{title}</b>\n\n{payload.get('text', '')}"
        documents = await self._documents(payload.get("media_file_ids") or [])
        return RenderedMessage(text_html=text_html, documents=documents)

    async def _documents(self, file_ids: list[Any]) -> tuple[tuple[str, bytes], ...]:
        documents: list[tuple[str, bytes]] = []
        for raw_id in file_ids:
            file_id = UUID(str(raw_id))
            try:
                ref = await self.files.get(file_id)
                if ref is None:
                    log.warning("broadcast_media_missing", file_id=str(file_id))
                    continue
                documents.append((ref.name, await self.files.read_bytes(file_id)))
            except BaseError:
                log.warning("broadcast_media_unreadable", file_id=str(file_id))
        return tuple(documents)
