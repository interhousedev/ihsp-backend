"""Public entry points: AI markdown to Telegram HTML chunks, complete or partial."""

import re
from dataclasses import replace

from app.interfaces.bot.richtext.blocks import join_blocks, parse_blocks
from app.interfaces.bot.richtext.chunking import TELEGRAM_TEXT_LIMIT, pack
from app.interfaces.bot.richtext.model import ButtonSpec, FormulaSpec, TelegramChunk
from app.shared.openui.degrade import degrade_to_markdown

_OPEN_BUTTON = re.compile(r"^\s*\[\[button:")


def render_telegram(markdown: str) -> list[TelegramChunk]:
    """Render markdown with LaTeX and button lines to Telegram HTML chunks.

    Args:
        markdown: Model output in markdown.

    Returns:
        Chunks of at most 4096 characters in HTML parse mode. Buttons go on the last
        chunk; complex display formulas are listed on the chunk where they start.
        An empty list means no text; a button-only reply yields one empty chunk.
    """
    blocks = parse_blocks(degrade_to_markdown(markdown))  # AI-OPENUI: no blocks here
    html, starts = join_blocks(blocks)
    texts, first_chunk = pack(html, starts, TELEGRAM_TEXT_LIMIT)
    formulas: dict[int, list[FormulaSpec]] = {}
    block_index = 0
    for block in blocks:
        if not block.html:
            continue
        if block.formulas and block_index in first_chunk:
            formulas.setdefault(first_chunk[block_index], []).extend(block.formulas)
        block_index += 1
    buttons: tuple[ButtonSpec, ...] = tuple(
        b for block in blocks for b in block.buttons
    )
    chunks = [
        TelegramChunk(text=text, formulas=tuple(formulas.get(index, ())))
        for index, text in enumerate(texts)
    ]
    if not chunks and buttons:
        chunks = [TelegramChunk(text="")]
    if chunks and buttons:
        chunks[-1] = replace(chunks[-1], buttons=buttons)
    return chunks


def render_partial(markdown: str) -> list[TelegramChunk]:
    """Render a streaming draft; unfinished constructs cannot leave tags open.

    Unclosed code fences and display math run to the end of the text, unclosed
    emphasis stays literal, and a trailing unfinished button line is hidden.

    Args:
        markdown: The text received so far.

    Returns:
        The same chunks as render_telegram would give for the draft.
    """
    lines = degrade_to_markdown(markdown).split("\n")  # AI-OPENUI
    last = lines[-1] if lines else ""
    if _OPEN_BUTTON.match(last) and "]]" not in last:
        lines.pop()
    return render_telegram("\n".join(lines))
