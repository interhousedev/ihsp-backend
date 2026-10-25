"""An uploaded EPUB whose package or container XML holds an entity bomb is refused."""

import io
import zipfile

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction.epub_text import extract_epub

import pytest
from defusedxml import DefusedXmlException

BILLION_LAUGHS = (
    b'<?xml version="1.0"?>'
    b"<!DOCTYPE lolz ["
    b'<!ENTITY lol "lol">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    b"]><lolz>&lol3;</lolz>"
)


def _epub(container: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
    return out.getvalue()


def test_entity_bomb_in_container_is_refused_not_expanded() -> None:
    with pytest.raises((TextExtractionError, DefusedXmlException)):
        extract_epub(_epub(BILLION_LAUGHS))
