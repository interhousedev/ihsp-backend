"""Identifiers, tokens and codes."""

import re
from uuid import UUID

from app.shared.ids import (
    SHORT_ID_ALPHABET,
    SHORT_ID_PREFERRED,
    b64_to_uuid,
    hash_token,
    new_id,
    random_digits,
    random_token,
    uuid_to_b64,
)

from hypothesis import given
from hypothesis import strategies as st


def test_short_id_alphabet_has_no_confusing_characters() -> None:
    """SL-2: no 0, O, o, I, L, l and no dot."""
    assert not set("0OoILl.") & set(SHORT_ID_ALPHABET)
    assert set(SHORT_ID_PREFERRED) <= set(SHORT_ID_ALPHABET)


@given(st.uuids())
def test_uuid_survives_the_base64_round_trip(value: UUID) -> None:
    """BOT-2: callback data packs a UUID into 22 characters and back."""
    packed = uuid_to_b64(value)

    assert len(packed) == 22
    assert ":" not in packed
    assert b64_to_uuid(packed) == value


def test_hash_token_is_64_hex_characters() -> None:
    """Tokens are stored as SHA-256 hex digests."""
    digest = hash_token("secret")

    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == hash_token("secret")
    assert digest != hash_token("Secret")


def test_new_id_is_a_time_ordered_uuid_version_7() -> None:
    """Row ids are UUIDv7 stdlib UUIDs, ordered by creation time."""
    first, second = new_id(), new_id()

    assert isinstance(first, UUID)
    assert first.version == 7
    assert first != second
    assert str(first)[:8] <= str(second)[:8]


def test_random_token_is_url_safe_and_unique() -> None:
    """256-bit tokens are URL safe."""
    token = random_token()

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert token != random_token()


def test_random_digits_has_the_requested_length() -> None:
    """OTP codes and room PINs are numeric."""
    code = random_digits(6)

    assert re.fullmatch(r"\d{6}", code)
