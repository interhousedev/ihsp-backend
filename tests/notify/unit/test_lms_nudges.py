"""LMS nudges: renderers in 3 locales, opt-in, quiet hours and dedupe."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Self
from uuid import UUID

from app.modules.notify.application.lms_nudges import QueueLmsNudges, is_quiet
from app.modules.notify.application.renderers.builtin import register_builtin_renderers
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.contracts.identity import UserPreferences
from app.shared.contracts.notify import RenderContext
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from tests.factories.notify import make_user
from tests.fakes.notify.files import FakeFilesApi
from tests.fakes.notify.links import FakeLinksApi

import pytest

URLS = UrlsSettings()
TUE_17 = dt.datetime(2026, 11, 24, 12, 0, tzinfo=dt.UTC)  # 17:00 Tashkent


@pytest.mark.parametrize(
    ("kind", "payload", "locale", "title", "path"),
    [
        (
            NotificationType.LMS_REVIEW_DUE,
            {"count": 5},
            "en",
            "Time to review",
            "/review/",
        ),
        (
            NotificationType.LMS_REVIEW_DUE,
            {"count": 5},
            "ru",
            "Пора повторить",
            "/review/",
        ),
        (
            NotificationType.LMS_STREAK_AT_RISK,
            {"streak": 4},
            "uz",
            "Seriyangiz xavf ostida",
            "/my/",
        ),
        (
            NotificationType.LMS_DEADLINE_SOON,
            {"quest_id": "q", "title": "<b>X</b>", "ends_on": "2026-11-25"},
            "ru",
            "Задание класса скоро закончится",
            "/my/",
        ),
    ],
)
async def test_renderer_has_title_escaped_body_and_lms_button(
    i18n: I18nCore,
    kind: NotificationType,
    payload: dict[str, Any],
    locale: str,
    title: str,
    path: str,
) -> None:
    registry = RendererRegistry()
    register_builtin_renderers(
        registry,
        i18n=i18n,
        urls=URLS,
        links=FakeLinksApi(),  # type: ignore[arg-type]
        files=FakeFilesApi(),  # type: ignore[arg-type]
    )
    renderer = registry.get(kind)
    assert renderer is not None
    user = make_user(Role.STUDENT, locale=locale)
    message = await renderer(
        payload, RenderContext(user=user, locale=locale, telegram_user_id=7)
    )
    assert message is not None
    assert message.text_html.startswith(f"<b>{title}</b>\n")
    assert "<b>X</b>" not in message.text_html
    assert message.buttons is not None
    assert message.buttons[0][0]["url"] == f"{URLS.lms}{path}"


@pytest.mark.parametrize(
    ("moment", "quiet"),
    [
        (TUE_17, False),
        (dt.datetime(2026, 11, 24, 16, 0, tzinfo=dt.UTC), True),  # 21:00
        (dt.datetime(2026, 11, 24, 2, 59, tzinfo=dt.UTC), True),  # 07:59
        (dt.datetime(2026, 11, 24, 3, 0, tzinfo=dt.UTC), False),  # 08:00
        (dt.datetime(2026, 11, 28, 12, 0, tzinfo=dt.UTC), True),  # Saturday
    ],
)
def test_quiet_hours_and_weekends(moment: dt.datetime, quiet: bool) -> None:
    assert is_quiet(moment) is quiet


@dataclass(frozen=True)
class Nudge:
    user_id: UUID
    type: str
    payload: dict[str, Any]


@dataclass
class World:
    now: dt.datetime = TUE_17
    prefs: dict[UUID, UserPreferences] = field(default_factory=dict)
    nudges: list[Nudge] = field(default_factory=list)
    rows: dict[str, NotificationDraft] = field(default_factory=dict)
    days: list[dt.date] = field(default_factory=list)

    def now_fn(self) -> dt.datetime:
        return self.now


class _Clock:
    def __init__(self, w: World) -> None:
        self.w = w

    def now(self) -> dt.datetime:
        return self.w.now


class _Identity:
    def __init__(self, w: World) -> None:
        self.w = w

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        return self.w.prefs.get(user_id, UserPreferences())


class _Source:
    def __init__(self, w: World) -> None:
        self.w = w

    async def list_nudge_candidates(self, day: dt.date) -> list[Nudge]:
        self.w.days.append(day)
        return self.w.nudges


class _Uow:
    def __init__(self, w: World) -> None:
        self.w = w
        self.pending: list[NotificationDraft] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def notify(self, *drafts: NotificationDraft) -> None:
        self.pending.extend(drafts)

    async def commit(self) -> None:
        for d in self.pending:  # the outbox ignores a repeated dedupe key
            self.w.rows.setdefault(d.dedupe_key, d)


def _use_case(w: World) -> QueueLmsNudges:
    return QueueLmsNudges(
        uow_factory=lambda: _Uow(w),  # type: ignore[arg-type,return-value]
        identity=_Identity(w),  # type: ignore[arg-type]
        clock=_Clock(w),
    )


async def test_only_opted_in_types_are_queued_and_reruns_dedupe() -> None:
    w = World()
    on, off = new_id(), new_id()
    w.prefs[on] = UserPreferences(lms_nudges=["lms_review_due", "lms_deadline_soon"])
    w.nudges = [
        Nudge(on, "lms_review_due", {"count": 3}),
        Nudge(on, "lms_streak_at_risk", {"streak": 2}),
        Nudge(on, "lms_deadline_soon", {"quest_id": "a", "title": "A", "ends_on": "x"}),
        Nudge(on, "lms_deadline_soon", {"quest_id": "b", "title": "B", "ends_on": "x"}),
        Nudge(off, "lms_review_due", {"count": 3}),  # default: all off
    ]
    report = await _use_case(w).execute(_Source(w))
    await _use_case(w).execute(_Source(w))

    assert (report.queued, report.opted_out) == (3, 2)
    assert sorted(w.rows) == [
        f"lms_nudge:lms_deadline_soon:{on}:2026-11-24:a",
        f"lms_nudge:lms_deadline_soon:{on}:2026-11-24:b",
        f"lms_nudge:lms_review_due:{on}:2026-11-24",
    ]
    assert w.days == [dt.date(2026, 11, 24)] * 2


async def test_nothing_is_read_or_queued_in_quiet_hours() -> None:
    w = World(now=dt.datetime(2026, 11, 24, 17, 0, tzinfo=dt.UTC))  # 22:00
    user = new_id()
    w.prefs[user] = UserPreferences(lms_nudges=["lms_review_due"])
    w.nudges = [Nudge(user, "lms_review_due", {"count": 1})]

    report = await _use_case(w).execute(_Source(w))

    assert report.quiet and not w.rows and not w.days
