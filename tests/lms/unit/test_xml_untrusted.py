"""Cartridge XML from an upload: entity bombs and external entities are refused."""

from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError
from app.modules.lms.domain.cartridge.xml_utils import parse_xml

import pytest

BILLION_LAUGHS = (
    b'<?xml version="1.0"?>'
    b"<!DOCTYPE lolz ["
    b'<!ENTITY lol "lol">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    b"]><lolz>&lol3;</lolz>"
)
EXTERNAL_ENTITY = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b"<r>&x;</r>"
)


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, EXTERNAL_ENTITY])
def test_hostile_entity_payloads_are_refused(payload: bytes) -> None:
    with pytest.raises(CartridgeInvalidError):
        parse_xml(payload, path="imsmanifest.xml")


def test_plain_xml_still_parses() -> None:
    root = parse_xml(b"<manifest><resource/></manifest>", path="imsmanifest.xml")
    assert root.tag == "manifest"
