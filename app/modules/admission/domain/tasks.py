"""Student tasks: a status board with steps and links, set by the student or staff.

Finishing every step never closes a task; only an explicit status change does.
"""

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.errors import CharLimitError, InvalidAnswerError

TaskStatus = Literal["planned", "in_progress", "in_review", "blocked", "done"]
TaskPriority = Literal["low", "medium", "high"]
TaskSource = Literal["student", "mentor", "counselor", "ai"]
LinkKind = Literal["external", "internal"]

STATUSES: Final[tuple[TaskStatus, ...]] = (
    "planned",
    "in_progress",
    "in_review",
    "blocked",
    "done",
)
PRIORITIES: Final[tuple[TaskPriority, ...]] = ("low", "medium", "high")
SOURCES: Final[tuple[TaskSource, ...]] = ("student", "mentor", "counselor", "ai")
LINK_KINDS: Final[tuple[LinkKind, ...]] = ("external", "internal")

TITLE_MAX: Final = 200
DESCRIPTION_MAX: Final = 4000
STEP_MAX: Final = 300
LABEL_MAX: Final = 80
URL_MAX: Final = 500
STEPS_MAX: Final = 30
LINKS_MAX: Final = 10
MIN_YEAR: Final = 2000
"""Earliest year a date may have; older dates are input mistakes."""
SUGGEST_MAX: Final = 8
"""Tasks the model suggests at most."""


def _bad(field_name: str, **params: object) -> InvalidAnswerError:
    return InvalidAnswerError(params={"field": field_name, **params})


def check_text(field_name: str, value: str, limit: int, *, required: bool) -> str:
    """Return the trimmed text; reject an empty required or an over-long one."""
    clean = value.strip()
    if (required and not clean) or len(clean) > limit:
        raise CharLimitError(
            params={"field": field_name, "limit": limit, "count": len(clean)}
        )
    return clean


@dataclass(frozen=True, slots=True)
class TaskLink:
    """A labelled link: an outside page or a route of this app."""

    label: str
    url: str
    kind: LinkKind = "external"


@dataclass(frozen=True, slots=True)
class TaskStep:
    """One checklist step, optionally with a link."""

    id: UUID
    title: str
    done: bool = False
    link: TaskLink | None = None


_INTERNAL_PATH: Final = re.compile(r"^/[A-Za-z0-9\-._~/%?=&#]*$")


def is_internal_path(url: str) -> bool:
    """A same-site path: no scheme, no `//`, no `..`, no control characters."""
    return (
        _INTERNAL_PATH.fullmatch(url) is not None
        and not url.startswith("//")
        and "/.." not in url
    )


def clean_link(link: TaskLink) -> TaskLink:
    """Trim a link and check that its kind matches its address."""
    label = check_text("link.label", link.label, LABEL_MAX, required=True)
    url = check_text("link.url", link.url, URL_MAX, required=True)
    if link.kind == "external":
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise _bad("link.url")
    elif link.kind == "internal":
        if not is_internal_path(url):
            raise _bad("link.url")
    else:
        raise _bad("link.kind")
    return TaskLink(label, url, link.kind)


def clean_links(links: Iterable[TaskLink]) -> tuple[TaskLink, ...]:
    """Validate the links of a task."""
    out = tuple(clean_link(x) for x in links)
    if len(out) > LINKS_MAX:
        raise _bad("links", limit=LINKS_MAX)
    return out


def clean_steps(steps: Iterable[TaskStep]) -> tuple[TaskStep, ...]:
    """Validate the steps of a task and keep their order."""
    out = tuple(
        replace(
            s,
            title=check_text("step.title", s.title, STEP_MAX, required=True),
            link=clean_link(s.link) if s.link else None,
        )
        for s in steps
    )
    if len(out) > STEPS_MAX:
        raise _bad("steps", limit=STEPS_MAX)
    return out


def check_deadline(deadline: dt.date | None, start: dt.date | None) -> dt.date | None:
    """Return the deadline; reject a year before 2000 or a date before the start."""
    if deadline is None:
        return None
    if deadline.year < MIN_YEAR:
        raise _bad("deadline", min_year=MIN_YEAR)
    if start is not None and deadline < start:
        raise _bad("deadline")
    return deadline


def check_start(start: dt.date | None) -> dt.date | None:
    """Return the start date; reject a year before 2000."""
    if start is not None and start.year < MIN_YEAR:
        raise _bad("start_date", min_year=MIN_YEAR)
    return start


@dataclass(slots=True)
class Task:
    """One task; the student is its assignee."""

    id: UUID
    student_id: UUID
    title: str
    description: str = ""
    status: TaskStatus = "planned"
    priority: TaskPriority = "medium"
    start_date: dt.date | None = None
    deadline: dt.date | None = None
    list_entry_id: UUID | None = None
    created_by: TaskSource = "student"
    creator_id: UUID | None = None
    steps: tuple[TaskStep, ...] = ()
    links: tuple[TaskLink, ...] = ()
    completed_at: dt.datetime | None = None
    lock_version: int = 0
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    @property
    def progress(self) -> tuple[int, int]:
        """Done steps and all steps."""
        return sum(1 for s in self.steps if s.done), len(self.steps)

    def is_overdue(self, today: dt.date) -> bool:
        """Whether an unfinished task is past its deadline."""
        return (
            self.status != "done"
            and self.deadline is not None
            and self.deadline < today
        )

    def set_status(self, status: str, now: dt.datetime) -> None:
        """Move to a status; `done` stamps the completion, any other clears it."""
        if status not in STATUSES:
            raise _bad("status")
        self.status = status
        self.completed_at = now if status == "done" else None

    def toggle_step(self, step_id: UUID, done: bool) -> None:
        """Check or uncheck a step; the task status is left alone."""
        if not any(s.id == step_id for s in self.steps):
            raise _bad("step")
        self.steps = tuple(
            replace(s, done=done) if s.id == step_id else s for s in self.steps
        )

    def validate(self) -> None:
        """Check every field of the task."""
        self.title = check_text("title", self.title, TITLE_MAX, required=True)
        self.description = check_text(
            "description", self.description, DESCRIPTION_MAX, required=False
        )
        if self.status not in STATUSES:
            raise _bad("status")
        if self.priority not in PRIORITIES:
            raise _bad("priority")
        if self.created_by not in SOURCES:
            raise _bad("created_by")
        self.start_date = check_start(self.start_date)
        self.deadline = check_deadline(self.deadline, self.start_date)
        self.steps = clean_steps(self.steps)
        self.links = clean_links(self.links)
