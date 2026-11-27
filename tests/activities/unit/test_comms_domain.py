"""Partner, Announcement, ContactRequest, PlannerItem, EventReport (spec 4.3, 4.10).

The implementation must provide, under `app.modules.activities.domain`:
  partner: PartnerKind (sponsor|partner|media), Partner(club_id|None, name, kind,
  logo_file_id,
    url, tier, since, until, public) .validate() (https-only url, name<=100 else
    PartnerInvalidError),
    .is_active(today), .is_public_visible(today) (public and active and logo approved)
  announcement: NO channel concept: the sender never picks app/Telegram/push; the
  notifier fans out per
    recipient and notify applies each person's preferences. Announcement has no
    `channels` attribute and
    compose() rejects a `channels=` keyword (TypeError). sanitize_html(text) ->
    telegram-safe subset (b,i,u,s,a href=https,code,pre; everything else
    stripped, javascript: hrefs removed); Announcement.compose(...), .schedule(at, now)
    (future only),
    .cancel() only while sent_at is None (AnnouncementStateError), .mark_sent(now, n);
    DAILY_LIMIT == 3; check_daily_limit(sent_today, is_staff) raises
    AnnouncementLimitError (platform staff
    SU/ACTIVITIES_ADMIN/ADMIN are exempt, a club owner who merely holds a global role in
    another capacity
    is not: the caller passes is_staff computed from the actor's roles, never from club
    ownership);
    parse_audience('members'|'team'|'event:<uuid>') -> (kind, uuid|None) else
    AnnouncementInvalidError
  contact: ContactRequest.create(club, name, email, body, ip, salt, honeypot);
    MAX_BODY == 2000; club must be visibility_public AND contact_enabled AND active
    (ContactNotAcceptedError); honeypot filled -> status 'spam'; body stripped of HTML
    to plain text;
    ip stored only as ip_hash (sha256 salted, hex), never raw; the module has NO public
    view of a message
    (messages are inbox-only; no `public_view`); ContactInvalidError (empty body, bad
    email, too long);
    copied_to_safeguarding = club.has_minor_members (copy goes to adult staff holding
    ACTIVITIES_ADMIN,
    never to the student-held SU role; the copy carries the message but not the sender's
    ip_hash)
  planner: PlannerKind (idea|task|milestone|event_plan|report), PlannerStatus
    (backlog|planned|doing|done), PlannerItem.move(status) (any forward or backward move
    allowed
    except from done only to doing), completion_ratio(items) -> done / total (0.0 for
    none)
  report: EventReport(event_id, summary, attendance_count, media_file_ids, outcomes,
  published);
    EventReport.draft(event, checked_in_count) sets attendance_count automatically;
    .publish(event) only when event.status == done (ReportStateError);
    in_timeline(event, report) -> event done and report published
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.modules.activities.domain.announcement import (
    DAILY_LIMIT,
    Announcement,
    AnnouncementInvalidError,
    AnnouncementLimitError,
    AnnouncementStateError,
    check_daily_limit,
    parse_audience,
    sanitize_html,
)
from app.modules.activities.domain.club import Club
from app.modules.activities.domain.contact import (
    MAX_BODY,
    ContactInvalidError,
    ContactNotAcceptedError,
    ContactRequest,
)
from app.modules.activities.domain.partner import (
    Partner,
    PartnerInvalidError,
    PartnerKind,
)
from app.modules.activities.domain.planner import (
    PlannerItem,
    PlannerStatus,
    completion_ratio,
)
from app.modules.activities.domain.report import (
    EventReport,
    ReportStateError,
    in_timeline,
)

import pytest

NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)
TODAY = date(2026, 11, 27)


# ---- partner ------------------------------------------------------------------


def partner(**kw: object) -> Partner:
    base: dict[str, object] = {
        "club_id": None,
        "name": "Acme",
        "kind": PartnerKind.SPONSOR,
        "logo_file_id": uuid4(),
        "url": "https://acme.uz",
        "tier": "gold",
        "since": TODAY - timedelta(days=10),
        "until": None,
        "public": True,
    }
    base.update(kw)
    return Partner(**base)  # type: ignore[arg-type]


def test_partner_url_must_be_https_and_name_bounded() -> None:
    partner().validate()
    for bad in (
        partner(url="http://acme.uz"),
        partner(url="javascript:alert(1)"),
        partner(name=""),
        partner(name="x" * 101),
    ):
        with pytest.raises(PartnerInvalidError):
            bad.validate()


def test_partner_activity_window() -> None:
    assert partner().is_active(TODAY)
    assert not partner(until=TODAY - timedelta(days=1)).is_active(TODAY)
    assert not partner(since=TODAY + timedelta(days=1)).is_active(TODAY)


def test_partner_public_visibility() -> None:
    assert partner().is_public_visible(TODAY)
    assert not partner(public=False).is_public_visible(TODAY)
    assert not partner(until=TODAY - timedelta(days=1)).is_public_visible(TODAY)


# ---- announcement -------------------------------------------------------------


def test_announcement_has_no_channel_concept() -> None:
    a = _ann()
    assert not hasattr(a, "channels") and not hasattr(a, "channel")
    with pytest.raises(TypeError):
        Announcement.compose(
            club_id=uuid4(),
            author_id=uuid4(),
            text="x",
            audience="members",
            channels=("app",),
        )  # type: ignore[call-arg]


def test_html_is_reduced_to_the_telegram_subset() -> None:
    out = sanitize_html(
        '<b>hi</b> <script>alert(1)</script><a href="javascript:x">bad</a>'
        '<a href="https://iht.uz">ok</a><img src=x onerror=y><i onclick="z">t</i>'
    )
    assert "<script" not in out
    assert "javascript:" not in out and "<img" not in out and "onclick" not in out
    assert "<b>hi</b>" in out and 'href="https://iht.uz"' in out


def test_audiences() -> None:
    eid = uuid4()
    assert parse_audience("members") == ("members", None)
    assert parse_audience("team") == ("team", None)
    assert parse_audience(f"event:{eid}") == ("event", eid)
    for bad in ("everyone", "event:", "event:not-a-uuid", ""):
        with pytest.raises(AnnouncementInvalidError):
            parse_audience(bad)


def test_daily_limit_is_3_except_for_platform_staff() -> None:
    assert DAILY_LIMIT == 3
    check_daily_limit(2, is_staff=False)
    with pytest.raises(AnnouncementLimitError):
        check_daily_limit(3, is_staff=False)
    check_daily_limit(500, is_staff=True)


def _ann() -> Announcement:
    return Announcement.compose(
        club_id=uuid4(),
        author_id=uuid4(),
        text="<b>Meet</b>",
        audience="members",
    )


def test_schedule_needs_a_future_time_and_cancel_only_before_sending() -> None:
    a = _ann()
    with pytest.raises(AnnouncementInvalidError):
        a.schedule(NOW - timedelta(minutes=1), NOW)
    a.schedule(NOW + timedelta(hours=1), NOW)
    a.cancel()
    b = _ann()
    b.mark_sent(NOW, 12)
    assert (b.sent_at, b.recipient_count) == (NOW, 12)
    with pytest.raises(AnnouncementStateError):
        b.cancel()


def test_cannot_send_twice() -> None:
    a = _ann()
    a.mark_sent(NOW, 1)
    with pytest.raises(AnnouncementStateError):
        a.mark_sent(NOW, 1)


# ---- contact ------------------------------------------------------------------


def contact_club(**kw: object):
    base = {
        "id": uuid4(),
        "visibility_public": True,
        "contact_enabled": True,
        "status": "active",
        "has_minor_members": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def msg(club: Club = None, **kw: object) -> ContactRequest:
    args: dict[str, object] = {
        "club": club or contact_club(),
        "name": "Vera",
        "email": "vera@example.com",
        "body": "Hello!",
        "ip": "203.0.113.9",
        "salt": "s3",
        "honeypot": "",
    }
    args.update(kw)
    return ContactRequest.create(**args)  # type: ignore[arg-type]


def test_contact_stores_a_hash_not_the_ip() -> None:
    m = msg()
    assert not m.is_spam and "203.0.113.9" not in repr(m)
    assert len(m.ip_hash) == 64 and m.ip_hash == msg().ip_hash
    assert msg(salt="other").ip_hash != m.ip_hash


@pytest.mark.parametrize(
    "club",
    [
        contact_club(visibility_public=False),
        contact_club(contact_enabled=False),
        contact_club(status="suspended"),
        contact_club(status="draft"),
    ],
)
def test_closed_clubs_do_not_accept_messages(club: object) -> None:
    with pytest.raises(ContactNotAcceptedError):
        msg(club)


@pytest.mark.parametrize(
    "kw",
    [
        {"body": ""},
        {"body": "  "},
        {"body": "x" * 2001},
        {"email": "nope"},
        {"name": ""},
    ],
)
def test_invalid_contact_input(kw: dict) -> None:
    with pytest.raises(ContactInvalidError):
        msg(**kw)


def test_body_at_the_limit_is_accepted_and_html_is_stripped() -> None:
    assert MAX_BODY == 2000
    msg(body="x" * 2000)
    assert "<" not in msg(body="hi <script>alert(1)</script><b>there</b>").body


def test_honeypot_marks_spam() -> None:
    assert msg(honeypot="http://spam").is_spam


def test_messages_have_no_public_view() -> None:
    import app.modules.activities.domain.contact as contact_module

    assert not hasattr(contact_module, "public_view")


# ---- planner ------------------------------------------------------------------


def _item(status: PlannerStatus) -> PlannerItem:
    return PlannerItem(
        club_id=uuid4(),
        kind="task",
        title="t",
        body="",
        assignee_id=None,
        due_at=None,
        status=status,
        event_id=None,
        term="2026-1",
    )


def test_planner_completion_ratio() -> None:
    assert completion_ratio([]) == 0.0
    items = [
        _item(PlannerStatus.DONE),
        _item(PlannerStatus.DONE),
        _item(PlannerStatus.DOING),
        _item(PlannerStatus.BACKLOG),
    ]
    assert completion_ratio(items) == 0.5


def test_a_done_item_can_only_be_reopened_to_doing() -> None:
    i = _item(PlannerStatus.DONE)
    with pytest.raises(ValueError):
        i.move(PlannerStatus.BACKLOG)
    i.move(PlannerStatus.DOING)
    assert i.status == PlannerStatus.DOING


# ---- report -------------------------------------------------------------------


def _event(status: str) -> Any:
    return SimpleNamespace(id=uuid4(), status=status)


def test_report_attendance_is_automatic() -> None:
    r = EventReport.draft(_event("done"), checked_in_count=17)
    assert r.attendance_count == 17 and r.published is False


def test_report_publishes_only_for_done_events() -> None:
    e = _event("scheduled")
    r = EventReport.draft(e, 0)
    with pytest.raises(ReportStateError):
        r.publish(e)
    e.status = "done"
    r.publish(e)
    assert r.published and in_timeline(e, r)
    assert not in_timeline(e, EventReport.draft(e, 0))
