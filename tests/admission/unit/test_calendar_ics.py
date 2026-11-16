"""ADM-CAL: ICS rendering, feed tokens, alarm offsets and list balance."""

import datetime as dt

from app.modules.admission.domain.calendar import (
    CalendarEntry,
    clean_offsets,
    end_of_day,
    new_token,
    render_ics,
    token_hash,
)
from app.modules.admission.domain.classification import balance

NOW = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)


def _entry(
    title: str = "Columbia, RD; deadline", all_day: bool = True
) -> CalendarEntry:
    day = dt.date(2027, 1, 1)
    return CalendarEntry(
        "uni:x:RD:2027-01-01",
        "university",
        title,
        day,
        end_of_day(day),
        all_day=all_day,
    )


def _unfold(text: str) -> list[str]:
    assert text.endswith("\r\n")
    return text.replace("\r\n ", "").split("\r\n")[:-1]


def test_ics_is_well_formed_with_alarms() -> None:
    """ADM-CAL-1: VCALENDAR/VEVENT/VALARM nest, CRLF, escaped text, folded."""
    text = render_ics(
        [_entry("Ü" * 60)],
        calendar_name="Deadlines",
        user_key="u",
        alarm_offsets=(7, 0),
        now=NOW,
    )
    assert all(len(ln.encode()) <= 75 for ln in text.split("\r\n"))
    lines = _unfold(text)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    assert lines.count("BEGIN:VEVENT") == 1 == lines.count("END:VEVENT")
    assert lines.count("BEGIN:VALARM") == 2
    assert "TRIGGER:-P7D" in lines and "TRIGGER:PT0S" in lines
    assert "DTSTART;VALUE=DATE:20270101" in lines
    text = render_ics(
        [_entry()], calendar_name="D", user_key="u", alarm_offsets=(), now=NOW
    )
    assert "SUMMARY:Columbia\\, RD\\; deadline" in _unfold(text)


def test_uid_is_stable_and_hides_keys() -> None:
    """ADM-CAL-2: the same entry gets the same UID; no raw key in the feed."""
    a = render_ics(
        [_entry()], calendar_name="D", user_key="u", alarm_offsets=(), now=NOW
    )
    b = render_ics(
        [_entry()],
        calendar_name="D",
        user_key="u",
        alarm_offsets=(),
        now=NOW + dt.timedelta(hours=1),
    )
    uid = [ln for ln in _unfold(a) if ln.startswith("UID:")]
    assert uid == [ln for ln in _unfold(b) if ln.startswith("UID:")]
    assert "uni:x" not in a


def test_token_hash_and_offsets() -> None:
    """ADM-CAL-3: tokens are random, hashed; offsets cleaned to 0..90, ≤5."""
    t1, t2 = new_token(), new_token()
    assert t1 != t2 and len(token_hash(t1)) == 64 and token_hash(t1) != t1
    assert clean_offsets([1, 7, 7, -1, 91, 0, 3, 14, 30]) == (30, 14, 7, 3, 1)


def test_balance_verdicts() -> None:
    """ADM-LIST-1: empty, too few, no safety, too many reach, balanced."""
    assert balance([]).status == "empty"
    assert balance(["reach"]).status == "too_few"
    assert balance(["reach", "target", "target", "target"]).status == "no_safety"
    assert balance(["reach"] * 3 + ["safety"]).status == "too_many_reach"
    assert balance(["reach", "target", "safety", None]).status == "balanced"
