"""GET /v1/me/rating: the overall student rating of the current academic year."""

import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query
from pydantic import BaseModel


class RatingYear(BaseModel):
    """The rated academic year."""

    label: str
    starts_on: dt.date
    ends_on: dt.date


class RatingWeightsResponse(BaseModel):
    """How the score is built (penalties are positive numbers here)."""

    base: float
    category_points: dict[str, float]
    level_points: dict[str, float]
    marks_threshold: float
    marks_points: float
    absence_points: float
    work_off_points: float


class RatingCertificate(BaseModel):
    """A certificate of the year with its points."""

    name: str
    category: str
    level: str | None
    points: float


class RatingBreakdown(BaseModel):
    """The parts of the caller's score (penalties negative)."""

    base: float
    certificates: list[RatingCertificate]
    certificate_points: float
    mark_average: float | None
    mark_count: int
    marks_points: float
    absences: int
    absence_points: float
    work_offs: int
    work_off_points: float


class RatingRow(BaseModel):
    """One ranked student."""

    place: int
    student_id: UUID
    full_name: str
    group_name: str
    score: float
    photo_url: str | None
    is_me: bool


class MyRatingRow(RatingRow):
    """The caller's row with the breakdown."""

    breakdown: RatingBreakdown


class OverallRatingResponse(BaseModel):
    """Top students, the caller's place and the weights."""

    academic_year: RatingYear | None
    weights: RatingWeightsResponse
    total: int
    top: list[RatingRow]
    me: MyRatingRow | None


async def get_overall_rating(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> OverallRatingResponse:
    """The lyceum's students ranked by the overall score of the year."""
    data: dict[str, Any] = await container.academic.marks.get_overall_rating.execute(
        actor, limit
    )
    return OverallRatingResponse.model_validate(data)
