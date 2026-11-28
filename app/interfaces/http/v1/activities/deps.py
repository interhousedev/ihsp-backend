"""Shared dependencies and serialisation of the activities routes."""

import datetime as dt
from collections.abc import Iterable
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.activities.domain.planner import PlannerItem
from app.shared.actor import Actor

from fastapi import Depends
from pydantic import BaseModel

ContainerDep = Annotated[Container, Depends(get_container)]
ActorDep = Annotated[Actor, Depends(get_actor)]

T = TypeVar("T")


class ItemsOut(BaseModel, Generic[T]):
    """A list of rows."""

    items: list[T]


def items(rows: Iterable[T]) -> "ItemsOut[T]":
    """The `{items: [...]}` envelope."""
    return ItemsOut(items=list(rows))


class IdOut(BaseModel):
    """A created thing."""

    id: str


class StatusOut(BaseModel):
    """A thing with its status."""

    id: str
    status: str


class LeftOut(BaseModel):
    """The caller left the club."""

    status: str = "left"


class LeaderRowOut(BaseModel):
    """One line of a points table."""

    rank: int
    display_name: str
    points: int


class PointEntryOut(BaseModel):
    """One points entry."""

    reason: str
    points: int
    at: dt.datetime


class MyPointsOut(BaseModel):
    """The caller's points in a club."""

    total: int
    entries: list[PointEntryOut]


class AttendanceRow(BaseModel):
    """Attendance and shift counts of a member."""

    user_id: UUID
    display_name: str
    attended: int
    shifts: int
    no_shows: int


class RatingAggregate(BaseModel):
    """Count and averages of ratings."""

    count: int
    avg: float | None
    aspects: dict[str, float]


class RatingCommentOut(BaseModel):
    """A rating comment; the author only when not anonymous."""

    id: UUID
    score: int
    aspects: dict[str, int]
    comment: str | None
    created_at: dt.datetime
    user_id: UUID | None = None


class RatingsSummaryOut(BaseModel):
    """Ratings of a club and its events."""

    events: RatingAggregate
    club: RatingAggregate
    comments: list[RatingCommentOut]


class PlannerBoardOut(BaseModel):
    """Planner items and the share done."""

    items: list[PlannerItem]
    completion: float


class TokenOut(BaseModel):
    """A check-in token."""

    token: str


class OptOutOut(BaseModel):
    """The leaderboard visibility choice."""

    opted_out: bool
