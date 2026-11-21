"""Prompt categories are derived deterministically; short answers are bounded."""

from typing import Any
from uuid import UUID

from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.application.essay_short_answers import EssayShortAnswers
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.essay_categories import (
    classify_group,
    classify_prompt,
)
from app.modules.admission.domain.essay_flow import (
    PromptRef,
    common_app_refs,
    prompt_key,
)
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes_flow import MemPrompts, MemShortAnswers
from tests.admission.unit.test_essays import Desk
from tests.admission.unit.test_items_service import ItemsUow

import pytest

U = UUID("00000000-0000-0000-0000-0000000000b1")


def _p(text: str, limit: int | None = 250, unit: str = "words") -> PromptRef:
    return PromptRef(prompt_key(U, 0), U, "U", 0, text, limit, unit)


def test_categories_by_owner_keywords_and_limit() -> None:
    assert classify_prompt(common_app_refs()[0]) == "personal_statement"
    assert classify_prompt(_p("Why are you interested in our university?")) == "why_us"
    assert classify_prompt(_p("Describe a community you belong to")) == "community"
    assert classify_prompt(_p("List your extracurricular activities")) == "activity"
    assert classify_prompt(_p("Which academic subject excites you?")) == "academic"
    assert classify_prompt(_p("Name a book you loved", 100)) == "short_answer"
    assert classify_prompt(_p("Name a book you loved", 600, "chars")) == "short_answer"
    assert classify_prompt(_p("Tell us something", 500)) == "other"
    assert classify_prompt(_p("Tell us something", None)) == "other"


def test_label_counts_and_group_vote_is_stable() -> None:
    plain = _p("Tell us something", 500)
    assert classify_prompt(plain, "Your community") == "community"
    group = [plain, _p("Why this college?"), _p("Why us?")]
    assert classify_group(group) == "why_us"
    assert classify_group(group) == classify_group(list(reversed(group)))
    assert classify_group([]) == "other"


def _svc(d: Desk, refs: list[PromptRef]) -> EssayShortAnswers:
    prompts, answers = MemPrompts(refs), MemShortAnswers()

    def uow() -> Any:
        u = ItemsUow(d.w.store, d.w.data)
        u.prompt_catalog = prompts  # type: ignore[attr-defined]
        u.short_answers = answers  # type: ignore[attr-defined]
        return u

    return EssayShortAnswers(uow, FlowGate(d.w.policy, d.consents))


async def test_short_answer_roundtrip_and_limits() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    ref = _p("Name a book", 100)
    svc = _svc(d, [ref])
    assert (await svc.get(ctx, ref.key)).word_count == 0
    saved = await svc.put(ctx, ref.key, "one two three")
    assert saved.word_count == 3
    assert (await svc.get(ctx, ref.key)).text == "one two three"
    with pytest.raises(ValidationFailedError):
        await svc.put(ctx, ref.key, "w " * 101)  # prompt limit 100
    wide = _svc(d, [_p("Name a book", 400)])
    with pytest.raises(ValidationFailedError):
        await wide.put(ctx, ref.key, "w " * 151)  # global cap 150
    with pytest.raises(AdmissionNotFoundError):
        await svc.put(ctx, prompt_key(new_id(), 0), "x")
