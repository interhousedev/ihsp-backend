"""Structured outputs of the item tasks (§9.1): no nullable or union parameters."""

from typing import Any, Final, Literal

from app.modules.admission.application.review_rubric import Dimension, Grade
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema

from pydantic import BaseModel

Gap = Literal["numbers", "role", "impact", "scale", "time", "outcome"]
Fit = Literal["strong", "some", "none"]
Horizon = Literal["current", "projected"]

MAX_QUESTIONS: Final = 4
MAX_OPTIONS: Final = 4
MAX_MISSING_FACTS: Final = 6


class AiDimension(BaseModel):
    """One graded dimension: evidence first, then the grade and a suggestion."""

    dim: Dimension
    evidence: str
    grade: Grade
    suggestion: str


class AiWordFit(BaseModel):
    """How the item carries one of the student's words."""

    word: str
    fit: Fit
    evidence: str


class AiClaimRef(BaseModel):
    """A metric whose number the rewrite uses."""

    metric_id: str
    horizon: Horizon


class AiRewrite(BaseModel):
    """A proposed position, organization and description."""

    position: str
    org: str
    description: str
    claim_refs: list[AiClaimRef]


class AiItemReview(BaseModel):
    """`ADMIT_ITEM_REVIEW` output."""

    dimensions: list[AiDimension]
    word_fit: list[AiWordFit]
    rewrite: AiRewrite
    missing_facts: list[str]
    injection_suspected: bool
    safeguarding: bool


class AiQuestion(BaseModel):
    """One interview question."""

    gap: Gap
    question: str
    why_it_matters: str
    options: list[str]


class AiInterview(BaseModel):
    """`ADMIT_ITEM_INTERVIEW` output."""

    questions: list[AiQuestion]
    ready_for_review: bool
    proposal: AiRewrite
    injection_suspected: bool
    safeguarding: bool


REVIEW_SCHEMA_NAME: Final = "admission_item_review"
INTERVIEW_SCHEMA_NAME: Final = "admission_item_interview"
REWRITE_SCHEMA_NAME: Final = "admission_item_rewrite"
REVIEW_SCHEMA: Final[dict[str, Any]] = to_strict_schema(AiItemReview)
INTERVIEW_SCHEMA: Final[dict[str, Any]] = to_strict_schema(AiInterview)
REWRITE_SCHEMA: Final[dict[str, Any]] = to_strict_schema(AiRewrite)
