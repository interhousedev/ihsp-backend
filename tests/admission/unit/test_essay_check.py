"""Essay check: rubric score, bands, verified quotes, gates."""

import unicodedata
from typing import Any

from app.modules.admission.application.essays import (
    _checked,
    band_of,
)
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    ConsentRequiredError,
    EssayTooShortError,
)
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import essays as prompts
from app.modules.admission.ports.consent import AI
from app.shared.ai_tasks import AiTask
from tests.admission.unit.test_essays import Desk
from tests.admission.unit.test_items_service import OTHER, STUDENT

import pytest

DIMS = prompts.DIMENSIONS
PARAS = [
    "First paragraph " + "alpha " * 30,
    "Second  paragraph\nwith  breaks " + "beta " * 30,
]
BODY = "\n\n".join(PARAS)


def reply(scores: list[int] | int = 3, **kw: Any) -> dict[str, Any]:
    each = scores if isinstance(scores, list) else [scores] * len(DIMS)
    return {
        "dimensions": [
            {"dim": d, "score": s, "quote": "", "comment": "c"}
            for d, s in zip(DIMS, each, strict=True)
        ],
        "prompt_fit": "yes",
        "prompt_fit_reason": "r",
        "strongest": "hook",
        "first_fix": "f",
        "flagged_paragraph": 0,
        "flagged_reason": "x",
        "summary": "s",
    } | kw


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (0, "weak"),
        (14, "weak"),
        (15, "developing"),
        (34, "developing"),
        (35, "solid"),
        (59, "solid"),
        (60, "strong"),
        (84, "strong"),
        (85, "exceptional"),
        (100, "exceptional"),
    ],
)
def test_band_edges(score: int, band: str) -> None:
    """ADM-INTL-4: band edges are 15, 35, 60 and 85."""
    assert band_of(score) == band


@pytest.mark.parametrize(
    ("total", "score", "band"),
    [
        (0, 0, "weak"),
        (4, 13, "weak"),
        (5, 17, "developing"),
        (10, 33, "developing"),
        (11, 37, "solid"),
        (17, 57, "solid"),
        (18, 60, "strong"),
        (25, 83, "strong"),
        (26, 87, "exceptional"),
        (30, 100, "exceptional"),
    ],
)
def test_score_is_sum_over_thirty(total: int, score: int, band: str) -> None:
    """ADM-INTL-4: score = round(sum * 100 / 30), band from the score."""
    scores = [min(5, max(0, total - 5 * i)) for i in range(6)]
    out = _checked(reply(scores), BODY, 100, None, True)
    assert (out.score, out.band) == (score, band)


def test_quote_must_be_verbatim_modulo_whitespace_and_nfc() -> None:
    """ADM-INTL-4: an unverifiable quote is dropped, a spacing difference is not."""
    body = unicodedata.normalize("NFD", "Café stories\n\nare   fun to tell " * 3)
    data = reply()
    data["dimensions"][0]["quote"] = "Café stories are fun"
    data["dimensions"][1]["quote"] = "invented sentence"
    out = _checked(data, body, 100, None, True)
    assert out.dimensions[0].quote == "Café stories are fun"
    assert out.dimensions[1].quote is None


def test_flagged_paragraph_clamped_and_text_from_essay() -> None:
    """ADM-INTL-4: the paragraph index is clamped; the text is the essay's."""
    high = _checked(reply(flagged_paragraph=99), BODY, 100, None, True)
    low = _checked(reply(flagged_paragraph=-4), BODY, 100, None, True)
    assert high.flagged_paragraph == 1 and low.flagged_paragraph == 0
    assert high.flagged_text and high.flagged_text.startswith("Second paragraph with")


def test_missing_dimensions_score_zero_in_canonical_order() -> None:
    """ADM-INTL-4: absent dimensions get 0, order is the rubric's."""
    data = reply()
    data["dimensions"] = [data["dimensions"][3], data["dimensions"][0]]
    out = _checked(data, BODY, 100, None, True)
    assert [d.dim for d in out.dimensions] == list(DIMS)
    assert [d.score for d in out.dimensions] == [3, 0, 0, 3, 0, 0]


def test_generic_flag_and_over_limit() -> None:
    """ADM-INTL-4: three weak dimensions mean generic; limit is computed in code."""
    out = _checked(reply([1, 1, 0, 5, 5, 5]), BODY, 700, 650, True)
    assert out.generic and out.over_limit and out.word_count == 700
    fine = _checked(reply(4), BODY, 600, 650, True)
    assert not fine.generic and not fine.over_limit


def test_no_prompt_means_unknown_fit() -> None:
    """ADM-INTL-4: without a prompt text the fit is unknown and unexplained."""
    out = _checked(reply(), BODY, 100, None, False)
    assert out.prompt_fit == "unknown" and out.prompt_fit_reason == ""
    assert _checked(reply(prompt_fit="bogus"), BODY, 1, None, True).prompt_fit == (
        "partial"
    )


async def _drafted(d: Desk, **fields: Any) -> Any:
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, fields)
    return ctx, await d.svc.save(ctx, e.id, e.lock_version, {"body": BODY})


async def test_check_end_to_end_uses_coach_task() -> None:
    """ADM-INTL-4: the check scores a saved draft through the coach task."""
    d = Desk(reply(4))
    ctx, e = await _drafted(d, prompt_text="Tell us about you", word_limit=650)
    out = await d.coach.check(ctx, e.id, "en")
    assert out.score == 80 and out.band == "strong"
    assert out.prompt_fit == "yes" and out.word_limit == 650
    assert d.w.ai.calls[0]["task"] == AiTask.ADMIT_ESSAY_COACH


async def test_check_too_short_never_calls_the_model() -> None:
    """ADM-INTL-4: under 50 words fails before any model call."""
    d = Desk(reply())
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {})
    await d.svc.save(ctx, e.id, e.lock_version, {"body": "too few words"})
    with pytest.raises(EssayTooShortError):
        await d.coach.check(ctx, e.id, "en")
    assert d.w.ai.calls == []


async def test_check_gates_owner_and_consent() -> None:
    """ADM-INTL-4: another student gets not-found; no consent is refused."""
    d = Desk(reply())
    ctx, e = await _drafted(d)
    d.consents.grants[OTHER] = frozenset({AI})
    with pytest.raises(AdmissionNotFoundError):
        await d.coach.check(await d.w.ctx(OTHER), e.id, "en")
    d.consents.grants[STUDENT] = frozenset()
    with pytest.raises(ConsentRequiredError):
        await d.coach.check(ctx, e.id, "en")
    assert d.w.ai.calls == []


async def test_check_prompt_and_schema_registered() -> None:
    """ADM-INTL-4: the builtin prompt renders and the schema is strict."""
    text = await BuiltinPrompts().text(AiTask.ADMIT_ESSAY_COACH, "check", "en")
    assert "hook" in text.lower() and "reflection" in text.lower()
    task, schema = prompts.SCHEMAS["check"]
    assert "check" in prompts.PROMPTS and task == "essay_check"
    assert schema["additionalProperties"] is False
