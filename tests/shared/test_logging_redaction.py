"""The structlog processor masks credentials before they reach a log line."""

from app.shared.logging import REDACTED, redact_secrets, redact_text


def test_tokens_are_masked() -> None:
    """Guest, invite and personal tokens never survive."""
    for token in ("gst_" + "a" * 30, "inv_" + "b" * 30, "ihsp_pat_" + "c" * 30):
        assert token not in redact_text(f"token={token} ok")


def test_authorization_key_is_masked() -> None:
    """The Authorization key is replaced whatever its value."""
    event = redact_secrets(None, "info", {"event": "x", "Authorization": "Bearer abc"})
    assert event["Authorization"] == REDACTED


def test_bearer_text_is_masked() -> None:
    """A Bearer credential inside free text is masked."""
    assert "abcdef123456" not in redact_text("Authorization: Bearer abcdef123456")


def test_admission_query_string_is_masked() -> None:
    """Query strings of admission URLs are dropped."""
    out = redact_text("GET /v1/admission/x?code=SECRET123 200")
    assert "SECRET123" not in out


def test_plain_text_is_untouched() -> None:
    """Ordinary messages are left alone."""
    assert redact_text("hello world") == "hello world"
