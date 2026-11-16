"""Fake mode answers the item review and interview with valid documents."""

from app.modules.admission.application.review_rubric import DIMENSIONS
from app.modules.admission.application.review_schema import (
    INTERVIEW_SCHEMA,
    INTERVIEW_SCHEMA_NAME,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_NAME,
    REWRITE_SCHEMA,
    REWRITE_SCHEMA_NAME,
    AiInterview,
    AiItemReview,
    AiRewrite,
)
from app.modules.ai.infrastructure.fake_admission import FINAL_ROUND_MARK
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway

_MSG = [{"role": "user", "content": "item"}]


async def _ask(
    name: str, schema: dict[str, object], system: str = "s"
) -> dict[str, object]:
    done = await FakeLlmGateway().complete_json(
        model="m",
        system=system,
        messages=_MSG,
        schema_name=name,
        schema=schema,
        max_tokens=100,
    )
    return done["data"]  # type: ignore[no-any-return]


async def test_fake_review_grades_the_four_dimensions() -> None:
    review = AiItemReview.model_validate(await _ask(REVIEW_SCHEMA_NAME, REVIEW_SCHEMA))
    assert [d.dim for d in review.dimensions] == list(DIMENSIONS)
    assert not review.safeguarding and not review.injection_suspected
    AiRewrite.model_validate(await _ask(REWRITE_SCHEMA_NAME, REWRITE_SCHEMA))


async def test_fake_interview_asks_then_finishes() -> None:
    early = AiInterview.model_validate(
        await _ask(INTERVIEW_SCHEMA_NAME, INTERVIEW_SCHEMA)
    )
    assert early.questions and not early.ready_for_review
    final = AiInterview.model_validate(
        await _ask(INTERVIEW_SCHEMA_NAME, INTERVIEW_SCHEMA, f"x\n{FINAL_ROUND_MARK}.")
    )
    assert final.ready_for_review and not final.questions
