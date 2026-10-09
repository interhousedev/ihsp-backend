"""Request bodies of the LMS learning endpoints (responses are the use case views)."""

from app.shared.srs import Rating

from pydantic import BaseModel, Field


class LearningJoinBody(BaseModel):
    """`POST /v1/lms/join`: an invite code."""

    code: str = Field(min_length=1, max_length=64)


class LearningAnswerBody(BaseModel):
    """`Answer`: the chosen options, a text or a number (one of them per question)."""

    option_ids: list[str] | None = Field(default=None, max_length=100)
    text: str | None = Field(default=None, max_length=10_000)
    number: float | None = Field(default=None, allow_inf_nan=False)
    pairs: dict[str, str] | None = Field(default=None, max_length=50)
    cells: list[str] | None = Field(default=None, max_length=900)
    texts: list[str] | None = Field(default=None, max_length=50)
    output: str | None = Field(default=None, max_length=10_000)


class LearningSaveAnswersBody(BaseModel):
    """`PUT /v1/lms/attempts/{id}/answers`: answers by question id."""

    answers: dict[str, LearningAnswerBody] = Field(max_length=500)


class LearningReviewCardBody(BaseModel):
    """`POST /v1/lms/steps/{step_id}/cards/{card_id}/review`: the rating button."""

    rating: Rating


class LearningOverrideScoreBody(BaseModel):
    """`POST /v1/lms/attempts/{id}/override`: the reviewer's score and comment."""

    score: float = Field(allow_inf_nan=False)
    comment: str = Field(min_length=1, max_length=1000)
