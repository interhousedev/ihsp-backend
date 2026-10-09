"""Response model of the mark planner (`GET /v1/me/subjects/{id}/planner`)."""

from typing import Literal

from app.interfaces.http.v1.me_marks.schemas import SubjectRef

from pydantic import BaseModel

MarkType = Literal["lesson", "midterm", "final"]
Control = Literal["midterm", "final"]
TargetStatus = Literal["secured", "needed", "not_reachable", "unknown"]
Assumption = Literal[
    "rounding",
    "controls_per_semester",
    "same_mark_on_remaining",
    "pending_as_lesson_average",
    "no_lesson_marks",
    "what_if",
]


class PlannerStat(BaseModel):
    """How many marks of one type there are and their average."""

    count: int
    average: float | None


class PlannerPrediction(BaseModel):
    """The semester mark if pending controls get the assumed marks."""

    value: float | None
    midterm: int | None
    final: int | None


class PlannerPair(BaseModel):
    """The lowest final that works when the midterm gets ``midterm``."""

    midterm: int
    min_final: int | None


class PlannerTarget(BaseModel):
    """What it takes to end the semester with one grade."""

    grade: Literal[5, 4, 3]
    threshold: float
    status: TargetStatus
    control: Control | None
    min_value: int | None
    min_both: int | None
    pairs: list[PlannerPair]


class PlannerRemaining(BaseModel):
    """How many midterm and final controls of the semester have no mark yet."""

    midterm: int
    final: int


class PlannerWhatIf(BaseModel):
    """A hypothetical mark that is part of the answer."""

    type: MarkType
    value: int


class SubjectPlannerResponse(BaseModel):
    """Predicted semester mark and the marks the controls must bring."""

    subject: SubjectRef
    semester: int
    lesson: PlannerStat
    midterm: PlannerStat
    final: PlannerStat
    semester_mark: float | None
    components: list[MarkType]
    missing: list[MarkType]
    remaining: PlannerRemaining
    pending: list[Control]
    predicted: PlannerPrediction
    targets: list[PlannerTarget]
    assumptions: list[Assumption]
    what_if: list[PlannerWhatIf]
