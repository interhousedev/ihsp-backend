from app.settings import BugsinkSettings, Settings
from app.shared.observability import SCRUBBED, init_observability, scrub_event


def test_bugsink_off_by_default() -> None:
    assert BugsinkSettings().dsn == ""
    assert init_observability(Settings(), "api") is False


def test_scrub_event_strips_auth_and_cookies() -> None:
    event = {
        "request": {
            "headers": {"Authorization": "Bearer x", "Accept": "json"},
            "cookies": {"sid": "1"},
        },
        "extra": {"access_token": "abc", "note": "ok"},
        "user": {"email": "a@b.c"},
    }
    out = scrub_event(event, {})
    assert out["request"]["headers"] == {"Authorization": SCRUBBED, "Accept": "json"}
    assert "cookies" not in out["request"]
    assert out["extra"] == {"access_token": SCRUBBED, "note": "ok"}
    assert "user" not in out
