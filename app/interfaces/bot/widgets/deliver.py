"""Choose and send the widgets of an answer, with the Markdown fallback."""

from dataclasses import dataclass

from app.interfaces.bot.assistant.render import render_final
from app.interfaces.bot.widgets.methods import SendWidget
from app.interfaces.bot.widgets.render import Widget, render_widget
from app.shared.openui.blocks import split_blocks
from app.shared.openui.degrade import block_markdown
from app.shared.openui.validate import validate_block

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WidgetPlan:
    """The answer text without its blocks, and one widget per block."""

    text: str
    blocks: list[tuple[str, Widget]]


def plan_widgets(
    body: str, *, viz_token: str | None, visualize_label: str
) -> WidgetPlan | None:
    """Widgets for every valid block of `body`, or None to keep the Markdown path.

    All or nothing: when one valid block has no widget form the whole answer stays
    in the Markdown rendering, so no block is lost or shown twice.
    """
    texts: list[str] = []
    blocks: list[tuple[str, Widget]] = []
    for part in split_blocks(body):
        if part.kind != "block" or validate_block(part.text):
            texts.append(part.raw if part.kind == "block" else part.text)
            continue
        widget = render_widget(
            part.text, viz_token=viz_token, visualize_label=visualize_label
        )
        if widget is None:
            return None
        blocks.append((part.text, widget))
    if not blocks:
        return None
    return WidgetPlan("".join(texts).strip(), blocks)


async def send_widgets(bot: Bot, chat_id: int, plan: WidgetPlan) -> None:
    """Send each widget; on an API error that block goes out as Markdown text."""
    for source, widget in plan.blocks:
        try:
            await bot(
                SendWidget(
                    chat_id=chat_id,
                    html=widget.html,
                    caption=widget.caption or None,
                    allow_queries=True,
                )
            )
        except TelegramAPIError as error:
            log.info("bot.widget.fallback", error=type(error).__name__)
            for chunk in render_final(block_markdown(source)):
                await bot.send_message(chat_id, chunk.html, parse_mode="HTML")
