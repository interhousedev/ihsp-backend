"""Text of TXT and Markdown files.

Most files are UTF-8, but Windows editors still save Russian and Uzbek texts as
UTF-16 (with a byte order mark) or in the Cyrillic code page 1251; reading those as
UTF-8 would turn every letter into a replacement character.
"""

import codecs

from app.modules.files.infrastructure.extraction.limits import MAX_TEXT_CHARS
from app.modules.files.ports.text_extractor import ExtractedText

_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_LEGACY = "cp1251"
_BAD = "\N{REPLACEMENT CHARACTER}"
_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
_GOOD_PER_BAD = 2  # a few broken bytes in a UTF-8 text keep it UTF-8


def _mostly_utf8(text: str) -> bool:
    """True when a lossy UTF-8 decoding has clearly more real letters than errors.

    Cyrillic in code page 1251 is almost never valid UTF-8, so such a text decodes
    to nearly nothing but replacement characters.
    """
    bad = text.count(_BAD)
    good = sum(1 for char in text if ord(char) > 127) - bad
    return good >= bad * _GOOD_PER_BAD


def _decode(data: bytes) -> str:
    """UTF-8 (BOM dropped), UTF-16 by its BOM, else Windows-1251 (Cyrillic)."""
    if data.startswith(_UTF16_BOMS):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        lossy = data.decode("utf-8", errors="replace").removeprefix(_BOM)
    if _mostly_utf8(lossy):
        return lossy
    return data.decode(_LEGACY, errors="replace")


def extract_plain(data: bytes) -> ExtractedText:
    """Decode the text; bytes that fit no encoding become replacement characters."""
    return ExtractedText(text=_decode(data)[:MAX_TEXT_CHARS])
