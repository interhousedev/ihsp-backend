from typing import Any

from app.settings import BugsinkSettings, Settings
from app.shared.observability import SCRUBBED, init_observability, scrub_event


def test_bugsink_off_by_default() -> None:
    assert BugsinkSettings().dsn == ""
    assert init_observability(Settings(), "api") is False


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
