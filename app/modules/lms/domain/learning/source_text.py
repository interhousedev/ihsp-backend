"""Step content as plain text for notebook sources (LMS-17: never the tests)."""

import json
import re
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.lms.domain.authoring.content_edit import FILE_REFERENCE
from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    StepContent,
    TextBlock,
    VideoBlock,
)

BLOCK_SEPARATOR = "\n\n"
# A link to a library book or material (`/item?id=<uuid>` or `/read?id=<uuid>`).
LIBRARY_REFERENCE: Final = re.compile(
    r"/(?:item|read)\?(?:[^\s)\"'&]*&)*(?:id|item)=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def export_text(content: StepContent) -> tuple[str, tuple[int, ...]]:
    """Return the readable text of a step and where each exported block starts.

    Text blocks give their Markdown, flash card blocks give ``Q: front`` and
    ``A: back`` for every card (cards separated by a blank line). Only these two
    kinds are exported: test blocks, with their questions, options, correct answers
    and explanations, never are. Blocks without text are skipped, so a step with
    only tests gives ``("", ())``.

    Returns:
        The blocks joined by a blank line, and the character offset of every
        exported block in that text.
    """
    pieces = [piece for block in content.blocks if (piece := _piece(block))]
    starts: list[int] = []
    offset = 0
    for piece in pieces:
        starts.append(offset)
        offset += len(piece) + len(BLOCK_SEPARATOR)
    return BLOCK_SEPARATOR.join(pieces), tuple(starts)


def _piece(block: object) -> str:
    """Return the text of one block, or '' for blocks that are not exported."""
    if isinstance(block, TextBlock):
        return block.markdown.strip()
    if isinstance(block, FlashcardsBlock):
        return BLOCK_SEPARATOR.join(
            f"Q: {card.front.strip()}\nA: {card.back.strip()}" for card in block.cards
        )
    return ""


@dataclass(frozen=True, slots=True)
class MaterialRefs:
    """What a step points at besides its own text."""

    videos: tuple[VideoBlock, ...]
    files: tuple[UUID, ...]
    library_items: tuple[UUID, ...]


def material_refs(content: StepContent) -> MaterialRefs:
    """Videos, attached files (not video uploads) and linked library items of a step."""
    videos = tuple(b for b in content.blocks if isinstance(b, VideoBlock))
    text = json.dumps(content.model_dump(mode="json"), ensure_ascii=False)
    files = tuple(dict.fromkeys(UUID(m) for m in FILE_REFERENCE.findall(text)))
    library = tuple(dict.fromkeys(UUID(m) for m in LIBRARY_REFERENCE.findall(text)))
    return MaterialRefs(videos=videos, files=files, library_items=library)


def video_text(block: VideoBlock, step_title: str) -> str:
    """The text of a video: its caption (or the step title) and where to watch it.

    No transcript store exists yet; when it does, the transcript goes here.
    """
    title = block.caption.strip() or step_title.strip() or "Video"
    where = block.url.strip() if block.source == "link" else "uploaded video"
    return f"Video: {title}\n{where}".strip()
