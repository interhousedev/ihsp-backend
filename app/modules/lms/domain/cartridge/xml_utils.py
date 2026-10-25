"""Namespace-agnostic, entity-free XML parsing for cartridge files.

Cartridges come in several versions (CC 1.0 to 1.3, Canvas extensions) whose
namespaces differ while the element names stay the same, so lookups use local
names only. Documents with a DTD or entity declarations are refused: nothing in a
cartridge needs them and they are how billion-laughs and XXE attacks start.
"""

import re
import xml.etree.ElementTree as ET  # noqa: N817 - the usual alias
from collections.abc import Iterator
from typing import Final

from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

_DOCTYPE: Final = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)
XML_BASE: Final = "{http://www.w3.org/XML/1998/namespace}base"


def parse_xml(data: bytes, *, path: str) -> ET.Element:
    """Parse a document and return its root element.

    Raises:
        CartridgeInvalidError: ``bad-xml`` for malformed XML or a DTD.
    """
    if _DOCTYPE.search(data[:4096]) or b"<!ENTITY" in data:
        raise CartridgeInvalidError(params={"reason": "bad-xml", "path": path[:200]})
    try:
        return DefusedET.fromstring(data)
    except (DefusedET.ParseError, DefusedXmlException) as exc:
        raise CartridgeInvalidError(
            params={"reason": "bad-xml", "path": path[:200]}
        ) from exc


def local(tag: object) -> str:
    """Return the local name of an element tag (``{ns}item`` -> ``item``)."""
    text = tag if isinstance(tag, str) else ""
    return text.rsplit("}", 1)[-1]


def namespace(tag: object) -> str:
    """Return the namespace URI of a tag, or an empty string."""
    text = tag if isinstance(tag, str) else ""
    return text[1:].split("}", 1)[0] if text.startswith("{") else ""


def children(element: ET.Element, name: str) -> Iterator[ET.Element]:
    """Yield the direct children with this local name."""
    for child in element:
        if local(child.tag) == name:
            yield child


def child(element: ET.Element | None, *names: str) -> ET.Element | None:
    """Follow a path of local names through first matching children."""
    current = element
    for name in names:
        if current is None:
            return None
        current = next(children(current, name), None)
    return current


def descendants(element: ET.Element, name: str) -> Iterator[ET.Element]:
    """Yield every descendant with this local name, in document order."""
    for node in element.iter():
        if node is not element and local(node.tag) == name:
            yield node


def text_of(element: ET.Element | None) -> str:
    """Return all text inside an element, stripped."""
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def lom_string(element: ET.Element | None) -> str:
    """Return the first ``string`` (LOM langstring) inside, or the element text."""
    if element is None:
        return ""
    found = next(descendants(element, "string"), None)
    return text_of(found if found is not None else element)
