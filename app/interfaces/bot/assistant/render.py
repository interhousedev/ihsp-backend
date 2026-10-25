"""Markdown answers as Telegram HTML through the richtext renderer."""

from dataclasses import dataclass, field

from app.interfaces.bot.richtext import (
    ButtonSpec,
    TelegramChunk,
    render_partial,
    render_telegram,
)

from aiogram.types import InlineKeyboardButton

DRAFT_TAIL = 3500  # a draft shows the end of a long answer (4096 is the limit)


@dataclass(slots=True)
class Chunk:
    """One Telegram message of the answer."""

    html: str
    rows: list[list[InlineKeyboardButton]] = field(default_factory=list)


def _chunk(item: TelegramChunk) -> Chunk:
    """Only link buttons survive: model output never carries callback data.

    A callback button from the model (or a prompt injection in a source it read)
    could forge an approval; approvals use server-made tokens only.
    """
    rows = [
        [InlineKeyboardButton(text=spec.label, url=spec.url)]
        for spec in item.buttons
        if _is_link(spec)
    ]
    return Chunk(item.text, rows)


def _is_link(spec: ButtonSpec) -> bool:
    return spec.url is not None and spec.callback_data is None


def render_final(markdown: str) -> list[Chunk]:
    """The whole answer as messages (formulas as text, buttons on the last one)."""
    return [_chunk(item) for item in render_telegram(markdown) if item.text.strip()]


def render_draft(markdown: str) -> str:
    """The unfinished answer as one message for the live draft (its last chunk)."""
    chunks = render_partial(markdown[-DRAFT_TAIL:])
    return chunks[-1].text if chunks else ""
