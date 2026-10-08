"""Lesson resources and the room page link before a lesson (UF-BOT-07)."""

from typing import Any
from uuid import UUID

from app.modules.notify.application.describe import describe, lesson_head
from app.modules.notify.application.format import esc
from app.modules.notify.application.renderers.described import (
    Buttons,
    is_staff,
    link_button,
)
from app.settings import UrlsSettings
from app.shared.contracts.links import LinksApi, ResourceRef
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.i18n.core import I18nContext, I18nCore
from app.shared.notifications import NotificationType


def _entry(resource: ResourceRef) -> str:
    return f"{esc(resource.short_url)} ({esc(resource.title)})"


class LessonResourcesRenderer:
    """Head line, room page with PIN, materials and attachments of one lesson."""

    def __init__(self, i18n: I18nCore, urls: UrlsSettings, links: LinksApi) -> None:
        """Store translations, app URLs and the links API."""
        self.i18n = i18n
        self.urls = urls
        self.links = links

    async def __call__(
        self, payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        """Render the message, or None when the lesson has no visible resources."""
        resources = await self.links.lesson_resources(UUID(str(payload["lesson_id"])))
        visible = [r for r in resources if not r.hidden]
        materials = [r for r in visible if r.role == "material"]
        attachments = [r for r in visible if r.role == "attachment"]
        if not materials and not attachments:
            return None
        t = self.i18n.get_context(ctx.locale)
        room_link = self._room_link(payload)
        lines = [esc(lesson_head(payload, t))]
        if room_link is not None:
            lines.append(
                esc(
                    t(
                        "notify-lesson-resources-room",
                        url=room_link,
                        pin=payload.get("room_pin", ""),
                    )
                )
            )
        lines += self._materials(t, materials)
        lines += self._attachments(t, attachments)
        return RenderedMessage(
            text_html="\n".join(lines),
            buttons=self._buttons(payload, ctx, t, room_link),
        )

    @staticmethod
    def _room_link(payload: dict[str, Any]) -> str | None:
        url = payload.get("room_url")
        if not url:
            return None
        pin = payload.get("room_pin")
        return f"{url}?pin={pin}" if pin else str(url)

    @staticmethod
    def _materials(t: I18nContext, materials: list[ResourceRef]) -> list[str]:
        label = esc(t("notify-lesson-resources-materials"))
        if len(materials) == 1:
            return [f"{label} {_entry(materials[0])}"]
        return [label, *(_entry(r) for r in materials)] if materials else []

    @staticmethod
    def _attachments(t: I18nContext, attachments: list[ResourceRef]) -> list[str]:
        if not attachments:
            return []
        return [
            esc(t("notify-lesson-resources-attachments")),
            *(f"{esc(r.author_first_name)} - {_entry(r)}" for r in attachments),
        ]

    def _buttons(
        self,
        payload: dict[str, Any],
        ctx: RenderContext,
        t: I18nContext,
        room_link: str | None,
    ) -> Buttons:
        row: list[dict[str, Any]] = []
        if room_link is not None:
            row.append({"text": t("notify-btn-open-room"), "url": room_link})
        lesson = describe(
            NotificationType.LESSON_RESOURCES,
            payload,
            ctx.locale,
            i18n=self.i18n,
            urls=self.urls,
            staff=is_staff(ctx.user),
        )
        if lesson.link is not None:
            row.append(link_button(t("notify-btn-open-lesson"), lesson.link, self.urls))
        return [row]
