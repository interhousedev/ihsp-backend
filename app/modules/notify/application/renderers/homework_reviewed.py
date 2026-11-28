"""Telegram notice to the student: homework graded or returned."""

from typing import Any

from app.modules.notify.application.describe import describe
from app.modules.notify.application.format import esc, fmt_date, join_names
from app.modules.notify.application.renderers.described import (
    DescribedRenderer,
    is_staff,
)
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.notifications import NotificationType


class HomeworkReviewedRenderer(DescribedRenderer):
    """Title, lesson, grade and the teacher's comment as a quote."""

    notification_type = NotificationType.HOMEWORK_REVIEWED
    link_button_key = "notify-homework-reviewed-button"

    async def __call__(
        self, payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        """Render the notice; no grade line for a returned submission."""
        description = describe(
            self.notification_type,
            payload,
            ctx.locale,
            i18n=self.i18n,
            urls=self.urls,
            staff=is_staff(ctx.user),
        )
        t = self.i18n.get_context(ctx.locale)
        subject = esc(join_names(payload.get("subject_names")))
        lines = [
            f"<b>{esc(description.title)}</b>",
            f"{subject} · {esc(fmt_date(payload.get('lesson_date')))}",
        ]
        returned = payload.get("review_status") == "returned"
        if not returned and payload.get("grade") is not None:
            grade = t("notify-homework-reviewed-grade", grade=payload["grade"])
            lines.append(esc(grade))
        if payload.get("comment_preview"):
            comment = esc(payload["comment_preview"])
            lines.append(f"<blockquote>{comment}</blockquote>")
        return RenderedMessage(
            text_html="\n".join(lines),
            buttons=self.buttons(payload, ctx, description),
        )
