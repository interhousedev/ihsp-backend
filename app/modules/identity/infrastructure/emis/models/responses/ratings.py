"""EMIS ratings response."""

from pydantic import BaseModel, ConfigDict, Field


class DailyRatingV1DTO(BaseModel):
    """One mark."""

    class_date: str
    rating: int


class RatingGroupV1DTO(BaseModel):
    """All marks of one type (Joriy, Oraliq or Yakuniy nazorat)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    daily_ratings: list[DailyRatingV1DTO] | None = Field(
        default=None, alias="dailyRatings"
    )


class RatingsV1DTO(BaseModel):
    """The ``result`` object of ``GET student-profiles/edu-subjects/{id}/ratings/``."""

    ratings: list[RatingGroupV1DTO] | None = None
    semester_rating: float | str | None = None
