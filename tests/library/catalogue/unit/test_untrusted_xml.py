"""An EPUB with an entity bomb or external entity in container.xml has no cover.

The parser is defusedxml: the entity bomb is refused instead of expanded, and a
SYSTEM entity never reads a local file.
"""

import io
import zipfile

from app.modules.library.application.catalogue.cover_extract import extract_cover
from app.modules.library.domain.enums import FileFormat

BILLION_LAUGHS = (
    b'<?xml version="1.0"?>'
    b"<!DOCTYPE lolz ["
    b'<!ENTITY lol "lol">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    b'<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">'
    b"]><lolz>&lol4;</lolz>"
)
EXTERNAL_ENTITY = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b"<r>&x;</r>"
)


def _epub_with_container(container: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
    return out.getvalue()


def test_billion_laughs_container_is_refused_and_yields_no_cover() -> None:
    data = _epub_with_container(BILLION_LAUGHS)
    assert extract_cover(data, FileFormat.EPUB) is None


def test_external_entity_container_is_refused_and_yields_no_cover() -> None:
    data = _epub_with_container(EXTERNAL_ENTITY)
    assert extract_cover(data, FileFormat.EPUB) is None
