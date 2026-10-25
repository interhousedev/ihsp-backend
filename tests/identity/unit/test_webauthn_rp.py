"""The py_webauthn relying party: RP id and origin from the IHT ID URL."""

from app.modules.identity.domain.errors import PasskeyInvalidError
from app.modules.identity.infrastructure.webauthn_rp import PyWebAuthn

import pytest


def test_rp_id_and_origin_come_from_the_id_url() -> None:
    """id.<domain> in production, the dev host locally."""
    prod = PyWebAuthn.for_url("https://id.ihsu.uz/")
    assert (prod.rp_id, prod.origin) == ("id.ihsu.uz", "https://id.ihsu.uz")
    dev = PyWebAuthn.for_url("http://id.localhost:3001")
    assert (dev.rp_id, dev.origin) == ("id.localhost", "http://id.localhost:3001")


def test_registration_options_ask_for_a_discoverable_verified_passkey() -> None:
    """Resident key required, user verification required, exclusions listed."""
    rp = PyWebAuthn.for_url("https://id.ihsu.uz")

    ceremony = rp.registration_options(
        user_id=b"u" * 16, user_name="a.b", display_name="A B", exclude=[b"old"]
    )

    options = ceremony.options
    assert options["rp"] == {"name": "IHT ID", "id": "id.ihsu.uz"}
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["excludeCredentials"][0]["id"] == "b2xk"
    assert len(ceremony.challenge) >= 32


def test_authentication_options_allow_any_passkey_of_the_site() -> None:
    """Empty allow list for conditional UI."""
    ceremony = PyWebAuthn.for_url("https://id.ihsu.uz").authentication_options()

    assert ceremony.options["rpId"] == "id.ihsu.uz"
    assert ceremony.options.get("allowCredentials", []) == []


def test_garbage_answers_raise_passkey_invalid() -> None:
    """Every library failure maps to one domain error."""
    rp = PyWebAuthn.for_url("https://id.ihsu.uz")
    junk = {"id": "AA", "rawId": "AA", "type": "public-key", "response": {}}

    with pytest.raises(PasskeyInvalidError):
        rp.verify_registration(junk, b"c" * 32)
    with pytest.raises(PasskeyInvalidError):
        rp.verify_authentication(junk, b"c" * 32, public_key=b"k", sign_count=0)
