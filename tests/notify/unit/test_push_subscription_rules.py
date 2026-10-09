"""Rules for accepting a Web Push subscription and building its payload."""

import json

from app.modules.notify.domain.errors import InvalidPushSubscriptionError
from app.modules.notify.domain.push_payload import MAX_PAYLOAD_BYTES, PushPayload
from app.modules.notify.domain.push_subscription import (
    validate_endpoint,
    validate_keys,
)
from app.settings import PUSH_ENDPOINT_SUFFIXES
from tests.factories.notify import AUTH, P256DH

import pytest


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/QAbc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
    ],
)
def test_endpoints_of_the_known_push_services_are_accepted(endpoint: str) -> None:
    """Chrome, Firefox, Safari and Edge use these services."""
    validate_endpoint(endpoint, PUSH_ENDPOINT_SUFFIXES)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",  # not https
        "https://localhost/push",
        "https://127.0.0.1/push",
        "https://169.254.169.254/latest/meta-data/",
        "https://evilgoogleapis.com/push",  # suffix without a dot boundary
        "https://fcm.googleapis.com.evil.example/push",
        "https://user:pw@fcm.googleapis.com/push",
        "https://fcm.googleapis.com:8443/push",
        "https://fcm.googleapis.com/" + "a" * 2100,
        "not a url",
    ],
)
def test_other_endpoints_are_refused_because_the_server_calls_them(
    endpoint: str,
) -> None:
    """SSRF guard: only https and known push services."""
    with pytest.raises(InvalidPushSubscriptionError) as caught:
        validate_endpoint(endpoint, PUSH_ENDPOINT_SUFFIXES)

    assert caught.value.params == {"field": "endpoint"}


def test_valid_keys_pass() -> None:
    """A 65-byte P-256 point and a 16-byte auth secret."""
    validate_keys(P256DH, AUTH)


@pytest.mark.parametrize(
    ("p256dh", "auth", "field"),
    [
        ("!!!", AUTH, "p256dh"),
        ("AAAA", AUTH, "p256dh"),  # wrong length
        (P256DH, "AAAA", "auth"),
        (P256DH, "***", "auth"),
    ],
)
def test_bad_keys_are_refused_with_the_field_name(
    p256dh: str, auth: str, field: str
) -> None:
    """The browser sees which key it got wrong."""
    with pytest.raises(InvalidPushSubscriptionError) as caught:
        validate_keys(p256dh, auth)

    assert caught.value.params == {"field": field}


def _payload(**overrides: str) -> PushPayload:
    values = {
        "title": "New marks",
        "body": "Algebra: 5",
        "url": "https://sp.ihsu.uz/grades/",
        "tag": "n1",
        "notification_id": "n1",
        "type": "marks",
    }
    return PushPayload(**{**values, **overrides})


def test_payload_json_has_exactly_the_contract_keys() -> None:
    """The service worker reads these six keys."""
    data = json.loads(_payload().to_json())

    assert data == {
        "title": "New marks",
        "body": "Algebra: 5",
        "url": "https://sp.ihsu.uz/grades/",
        "tag": "n1",
        "notification_id": "n1",
        "type": "marks",
    }


def test_payload_keeps_non_ascii_text_readable() -> None:
    """No \\u escapes: they would waste the byte budget."""
    text = _payload(title="Оценки").to_json()

    assert "Оценки" in text


@pytest.mark.parametrize("char", ["a", "я", "ў", "😀"])
def test_long_text_is_cut_to_the_byte_limit(char: str) -> None:
    """The limit is in bytes after UTF-8, whatever the script."""
    payload = _payload(title=char * 500, body=char * 20_000)

    text = payload.to_json()

    assert len(text.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    data = json.loads(text)
    assert data["body"].endswith("…") and data["url"] == payload.url


def test_a_huge_url_still_leaves_valid_json_within_the_limit() -> None:
    """Title and body shrink before the payload breaks the limit."""
    text = _payload(url="https://sp.ihsu.uz/x?" + "q" * 2500, body="b" * 900).to_json()

    assert len(text.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert json.loads(text)["tag"] == "n1"
