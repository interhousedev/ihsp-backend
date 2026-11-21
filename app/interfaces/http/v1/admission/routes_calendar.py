"""Deadline calendar routes (`/v1/admission/calendar*`).

The calendar merges university, checklist, exam and opportunity deadlines.
`GET /calendar/{token}.ics` is public: the token in the path is the only
credential, it is stored hashed, and the feed carries titles and dates only.
"""

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.calendar import FeedStatus
from app.modules.admission.domain.calendar import (
    MAX_ALARMS,
    MAX_OFFSET_DAYS,
    CalendarEntry,
    ExamDate,
)

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Lang = Annotated[str | None, Header(alias="Accept-Language")]
Exam = Literal["ielts", "toefl", "duolingo", "sat", "act"]


async def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


class CalendarEntryOut(BaseModel):
    """One dated item; `day` is the Tashkent calendar day."""

    key: str
    source: Literal["university", "checklist", "exam", "opportunity", "test_score"]
    title: str
    day: dt.date
    due_utc: dt.datetime
    all_day: bool
    url_path: str | None
    predicted: bool
    remind: bool
    list_entry_id: UUID | None

    @classmethod
    def of(cls, e: CalendarEntry) -> "CalendarEntryOut":
        """Map the domain entry."""
        return cls(
            key=e.key,
            source=e.source,
            title=e.title,
            day=e.day,
            due_utc=e.due_utc,
            all_day=e.all_day,
            url_path=e.url_path,
            predicted=e.predicted,
            remind=e.remind,
            list_entry_id=e.list_entry_id,
        )


class CalendarOut(BaseModel):
    """Entries in the range, earliest first, and the registered sources."""

    items: list[CalendarEntryOut]
    sources: list[str]


class FeedStatusOut(BaseModel):
    """My feed; the URL is shown only when the feed is created or rotated."""

    active: bool
    created_at: dt.datetime | None
    alarm_offsets: list[int]
    default_offsets: list[int]
    max_alarms: int = MAX_ALARMS
    max_offset_days: int = MAX_OFFSET_DAYS

    @classmethod
    def of(cls, s: FeedStatus) -> "FeedStatusOut":
        """Map the status."""
        return cls(
            active=s.active,
            created_at=s.created_at,
            alarm_offsets=list(s.alarm_offsets),
            default_offsets=list(s.default_offsets),
        )


class IssuedFeedOut(BaseModel):
    """A new feed. `path` is relative to the API origin; keep it private."""

    path: str
    status: FeedStatusOut


class AlarmsIn(BaseModel):
    """Alarm offsets in days before the deadline; empty means the defaults."""

    offsets: list[Annotated[int, Field(ge=0, le=MAX_OFFSET_DAYS)]] = Field(
        max_length=MAX_ALARMS
    )


class ExamDateOut(BaseModel):
    """An exam's test day and its registration deadline."""

    id: UUID
    exam: Exam
    test_date: dt.date
    registration_deadline: dt.date
    source_url: str | None

    @classmethod
    def of(cls, e: ExamDate) -> "ExamDateOut":
        """Map the domain record."""
        return cls(
            id=e.id,
            exam=e.exam,
            test_date=e.test_date,
            registration_deadline=e.registration_deadline,
            source_url=e.source_url,
        )


class ExamDateIn(BaseModel):
    """A new exam date (staff)."""

    exam: Exam
    test_date: dt.date
    registration_deadline: dt.date
    source_url: str | None = Field(default=None, max_length=500)


async def get_calendar(
    container: ContainerDep,
    ctx: AdmissionCtx,
    start: Annotated[dt.date, Query(alias="from")],
    end: Annotated[dt.date, Query(alias="to")],
    student_id: Annotated[UUID | None, Query()] = None,
    accept_language: Lang = None,
) -> CalendarOut:
    """My calendar or a student's, between two days (at most 400 days)."""
    cal = container.admission.calendar
    rows = await cal.entries(
        ctx, start, end, _locale(accept_language), student_id=student_id
    )
    return CalendarOut(
        items=[CalendarEntryOut.of(e) for e in rows], sources=list(cal.sources)
    )


async def get_feed(container: ContainerDep, ctx: AdmissionCtx) -> FeedStatusOut:
    """Whether I have a calendar feed, and its alarms."""
    return FeedStatusOut.of(await container.admission.calendar.feed_status(ctx))


async def issue_feed(
    container: ContainerDep, ctx: AdmissionCtx, accept_language: Lang = None
) -> IssuedFeedOut:
    """Create my feed, or rotate it (the old URL stops working)."""
    issued = await container.admission.calendar.issue_feed(
        ctx, _locale(accept_language)
    )
    return IssuedFeedOut(path=issued.path, status=FeedStatusOut.of(issued.status))


async def revoke_feed(container: ContainerDep, ctx: AdmissionCtx) -> None:
    """Revoke my feed."""
    await container.admission.calendar.revoke_feed(ctx)


async def set_feed_alarms(
    body: AlarmsIn, container: ContainerDep, ctx: AdmissionCtx
) -> FeedStatusOut:
    """Set the reminder alarms of my feed."""
    return FeedStatusOut.of(
        await container.admission.calendar.set_alarms(ctx, body.offsets)
    )


async def get_feed_ics(token: str, container: ContainerDep) -> Response:
    """The public ICS feed of a token (no sign-in; unknown and revoked: 404)."""
    body = await container.admission.calendar.ics(token)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex",
        },
    )


async def list_exam_dates(
    container: ContainerDep, ctx: AdmissionCtx
) -> list[ExamDateOut]:
    """All exam dates (staff with `deadlines:manage`)."""
    rows = await container.admission.calendar.exam_dates(ctx)
    return [ExamDateOut.of(e) for e in rows]


async def add_exam_date(
    body: ExamDateIn, container: ContainerDep, ctx: AdmissionCtx
) -> ExamDateOut:
    """Add an exam date (staff with `deadlines:manage`)."""
    item = await container.admission.calendar.add_exam_date(
        ctx,
        exam=body.exam,
        test_date=body.test_date,
        registration_deadline=body.registration_deadline,
        source_url=body.source_url,
    )
    return ExamDateOut.of(item)


async def delete_exam_date(
    exam_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> None:
    """Delete an exam date (staff with `deadlines:manage`)."""
    await container.admission.calendar.delete_exam_date(ctx, exam_id)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_route("/calendar", get_calendar, "GET", "get_calendar", response_model=CalendarOut)
_route(
    "/calendar/feed", get_feed, "GET", "get_calendar_feed", response_model=FeedStatusOut
)
_route(
    "/calendar/feed",
    issue_feed,
    "POST",
    "issue_calendar_feed",
    response_model=IssuedFeedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_no_store)],
)
_route(
    "/calendar/feed",
    revoke_feed,
    "DELETE",
    "revoke_calendar_feed",
    status_code=status.HTTP_204_NO_CONTENT,
)
_route(
    "/calendar/feed/alarms",
    set_feed_alarms,
    "PUT",
    "set_calendar_feed_alarms",
    response_model=FeedStatusOut,
)
_route(
    "/calendar/exams",
    list_exam_dates,
    "GET",
    "list_exam_dates",
    response_model=list[ExamDateOut],
)
_route(
    "/calendar/exams",
    add_exam_date,
    "POST",
    "add_exam_date",
    response_model=ExamDateOut,
    status_code=status.HTTP_201_CREATED,
)
_route(
    "/calendar/exams/{exam_id}",
    delete_exam_date,
    "DELETE",
    "delete_exam_date",
    status_code=status.HTTP_204_NO_CONTENT,
)
_route(
    "/calendar/{token}.ics",
    get_feed_ics,
    "GET",
    "get_calendar_ics",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
