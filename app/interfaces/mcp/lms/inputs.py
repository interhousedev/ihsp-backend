"""Argument models of the LMS Course server (shown to AI clients as JSON schema)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class OptionInput(BaseModel):
    """One answer option of a single or multiple choice question."""

    text: str = Field(min_length=1, max_length=500, description="Option text.")
    correct: bool = Field(default=False, description="True for a correct option.")
    pinned: bool = Field(
        default=False,
        description=(
            "Keep this option in place when options are shuffled, "
            'e.g. "None of the above".'
        ),
    )


class QuestionInput(BaseModel):
    """A test question. Fill the fields that belong to its type."""

    type: Literal["single", "multiple", "text", "number"] = Field(
        description="single: one correct option; multiple: several; text; number."
    )
    prompt: str = Field(min_length=1, max_length=2000, description="Question text.")
    points: int = Field(
        default=1, ge=1, le=100, description="Score for a right answer."
    )
    explanation: str | None = Field(
        default=None, max_length=2000, description="Shown after answering, if allowed."
    )
    options: list[OptionInput] | None = Field(
        default=None,
        max_length=10,
        description="For single and multiple: at least two options.",
    )
    accepted_answers: list[str] | None = Field(
        default=None, max_length=20, description="For text: accepted exact answers."
    )
    regex: str | None = Field(
        default=None, max_length=200, description="For text: a regular expression."
    )
    case_sensitive: bool = Field(
        default=False, description="For text: compare case-sensitively."
    )
    number: float | None = Field(
        default=None, description="For number: the right value."
    )
    tolerance: float = Field(
        default=0.0, ge=0, description="For number: allowed difference."
    )


class QuizSettingsInput(BaseModel):
    """Settings of a test block; omitted fields get the defaults shown."""

    max_attempts: int | None = Field(
        default=None, ge=1, le=100, description="Attempts per student; null: unlimited."
    )
    passing_score_pct: int = Field(default=60, ge=0, le=100)
    shuffle_questions: bool = False
    shuffle_options: bool = False
    pool_size: int | None = Field(
        default=None, ge=1, description="Ask N random questions of the pool; null: all."
    )
    time_limit_sec: int | None = Field(default=None, ge=30)
    cooldown_sec: int | None = Field(default=None, ge=0)
    show_answers: Literal[
        "never", "after_submit", "after_pass", "after_last_attempt"
    ] = "after_submit"


QuestionList = Annotated[
    list[QuestionInput],
    Field(max_length=50, description="Questions to add (at most 50)."),
]
