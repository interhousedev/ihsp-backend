"""Responses of the Administration logs."""

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel


class LogLevel(StrEnum):
    """Severity of an error issue."""

    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


class LogIssue(BaseModel):
    """One grouped error issue."""

    id: str
    title: str
    level: str
    count: int
    last_seen: dt.datetime | None
    project: str
    url: str
    """Deep link to the issue page in Bugsink."""


class LogIssuesPage(BaseModel):
    """A page of issues; empty with ``disabled`` when Bugsink is not configured."""

    items: list[LogIssue]
    page: int
    size: int
    has_next: bool
    projects: list[str]
    """Project ids offered by the filter."""
    disabled: bool
