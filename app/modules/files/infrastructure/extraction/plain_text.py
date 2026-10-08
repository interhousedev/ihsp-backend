"""Text of TXT and Markdown files."""

from app.modules.files.infrastructure.extraction.limits import MAX_TEXT_CHARS
from app.modules.files.ports.text_extractor import ExtractedText


def extract_plain(data: bytes) -> ExtractedText:
    """Decode UTF-8 and replace bytes that are not valid UTF-8."""
    text = data.decode("utf-8", errors="replace").removeprefix("﻿")
    return ExtractedText(text=text[:MAX_TEXT_CHARS])
