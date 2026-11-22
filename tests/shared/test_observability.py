from typing import Any

from app.settings import BugsinkSettings, Settings
from app.shared.observability import SCRUBBED, init_observability, scrub_event


def test_bugsink_off_by_default() -> None:
    assert BugsinkSettings().dsn == ""
    assert init_observability(Settings(), "api") is False


def test_scrub_event_drops_frame_locals_and_key_material() -> None:
    frame = {"function": "seal", "vars": {"dek": "secret", "text": "my essay"}}
    event: Any = {
        "exception": {"values": [{"stacktrace": {"frames": [dict(frame)]}}]},
        "threads": {"values": [{"stacktrace": {"frames": [dict(frame)]}}]},
        "extra": {
            "passphrase": "p",
            "dek": "k",
            "pending_dek": "k2",
            "plaintext": "t",
            "body": "essay",
            "essay_body": "essay",
            "note": "ok",
        },
    }
    out: Any = scrub_event(event, {})
    for section in ("exception", "threads"):
        (shown,) = out[section]["values"][0]["stacktrace"]["frames"]
        assert shown == {"function": "seal"}
    extra = out["extra"]
    assert extra.pop("note") == "ok"
    assert set(extra.values()) == {SCRUBBED}


def test_scrub_event_strips_auth_and_cookies() -> None:
    event: Any = {
        "request": {
            "headers": {"Authorization": "Bearer x", "Accept": "json"},
            "cookies": {"sid": "1"},
        },
        "extra": {"access_token": "abc", "note": "ok"},
        "user": {"email": "a@b.c"},
    }
    out: Any = scrub_event(event, {})
    assert out["request"]["headers"] == {"Authorization": SCRUBBED, "Accept": "json"}
    assert "cookies" not in out["request"]
    assert out["extra"] == {"access_token": SCRUBBED, "note": "ok"}
    assert "user" not in out


def test_scrub_event_masks_body_breadcrumbs_and_log_text() -> None:
    event: Any = {
        "request": {"data": '{"password": "hunter2"}'},
        "breadcrumbs": {
            "values": [
                {"message": "mail sent to pupil@school.uz", "data": {"to": "x@y.uz"}},
                {"category": "http", "data": {"api_key": "k1", "url": "/a"}},
            ]
        },
        "logentry": {"message": "login %s token=abc123", "params": ["a@b.co"]},
        "message": "bearer xyz789 rejected",
    }
    out: Any = scrub_event(event, {})
    assert out["request"]["data"] == SCRUBBED
    crumbs = out["breadcrumbs"]["values"]
    assert crumbs[0]["message"] == f"mail sent to {SCRUBBED}"
    assert crumbs[0]["data"] == {"to": SCRUBBED}
    assert crumbs[1]["data"] == {"api_key": SCRUBBED, "url": "/a"}
    assert out["logentry"]["params"] == [SCRUBBED]
    assert "abc123" not in out["logentry"]["message"]
    assert out["message"] == f"bearer {SCRUBBED} rejected"


def test_scanner_and_pdf_noise_is_dropped_but_real_errors_stay() -> None:
    """aiosmtpd scanner chatter, TLS setup failures and pypdf font warnings."""
    from app.shared.observability import before_send

    noise: list[Any] = [
        {
            "logger": "mail.log",
            "logentry": {"message": "('1.2.3.4', 5) unrecognised: X"},
        },
        {"logger": "mail.log", "message": "('1.2.3.4', 5) too many bogus commands"},
        {
            "logger": "mail.log",
            "exception": {"values": [{"type": "TLSSetupException"}]},
        },
        {"logger": "pypdf._cmap", "message": "fontTools is required to parse"},
    ]
    for event in noise:
        assert before_send(event, {}) is None
    real: Any = {"logger": "mail.log", "message": "Server exception: boom"}
    assert before_send(real, {}) is not None
    wrapped: Any = {
        "logger": "mail.log",
        "exception": {
            "values": [{"type": "TLSSetupException"}, {"type": "RuntimeError"}]
        },
    }
    assert before_send(wrapped, {}) is not None
    elsewhere: Any = {"exception": {"values": [{"type": "TLSSetupException"}]}}
    assert before_send(elsewhere, {}) is not None
