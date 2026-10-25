"""EMIS ratings response."""

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class DailyRatingV1DTO(BaseModel):
    """One mark; ``absent`` is read if EMIS ever sends an absence flag ("nb")."""

    class_date: str
    rating: int | None = None
    absent: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("absent", "is_absent", "nb", "is_nb"),
    )


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
    absences: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "absences", "absences_count", "missed_classes", "nb_count", "davomat"
        ),
    )
