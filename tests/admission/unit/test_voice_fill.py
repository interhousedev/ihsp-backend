"""Voice fill: value cleaning, consent, rate limit, fake mode; brief future interest."""

from typing import Any

from app.modules.admission.application.project_ideas import (
    brief_lines,
    search_queries,
)
from app.modules.admission.application.voice_fill import (
    VoiceField,
    VoiceFillService,
    clean_values,
    voice_lines,
)
from app.modules.admission.domain.errors import ConsentRequiredError
from app.modules.admission.domain.project_ideas import clean_brief
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import project_ideas, voice_fill
from app.modules.admission.ports.consent import AI
from app.modules.ai.infrastructure.fake_voice_fill import build_voice_fill_document
from app.shared.base_error import RateLimitedError, ValidationFailedError
from tests.admission.unit.fakes import FakeConsents
from tests.admission.unit.test_goal_plan import _Hits
from tests.admission.unit.test_items_service import STUDENT, World
from tests.admission.unit.test_project_ideas import BRIEF

import pytest

FIELDS = [
    VoiceField("likes", "What do you like?", "text"),
    VoiceField("hours", "Hours per day", "number"),
    VoiceField("team", "Teammates", "choice", ("yes", "maybe", "no")),
]


def test_clean_values_validates_by_kind_and_key() -> None:
    out = clean_values(
        {
            "values": [
                {"key": "likes", "value": " chess <b>and</b> robots "},
                {"key": "hours", "value": "about 2,5 hours"},
                {"key": "team", "value": "MAYBE"},
                {"key": "ghost", "value": "x"},
                {"key": "likes", "value": "again"},
            ]
        },
        FIELDS,
    )
    assert out["hours"] == "2.5" and out["team"] == "maybe"
    assert "ghost" not in out and "again" not in out.values()
    bad = clean_values(
        {"values": [{"key": "team", "value": "all"}, {"key": "hours", "value": "x"}]},
        FIELDS,
    )
    assert bad == {}


def test_fake_document_is_deterministic_and_matches_the_schema() -> None:
    lines = "\n".join(voice_lines(FIELDS, "I like chess", "en"))
    doc = build_voice_fill_document("voice_fill", [{"content": lines}])
    assert doc is not None
    assert clean_values(doc, FIELDS) == {
        "likes": "I like chess",
        "hours": "2",
        "team": "yes",
    }
    assert build_voice_fill_document("other", []) is None
    props = voice_fill.SCHEMA["properties"]["values"]["items"]
    assert props["additionalProperties"] is False


def _svc(w: World, *, consent: bool = True) -> VoiceFillService:
    return VoiceFillService(
        w.ai,  # type: ignore[arg-type]
        FakeConsents({STUDENT: frozenset({AI} if consent else set())}),
        BuiltinPrompts(),
        _Hits(),  # type: ignore[arg-type]
    )


async def test_fill_needs_consent_valid_input_and_is_limited() -> None:
    reply: dict[str, Any] = {"values": [{"key": "likes", "value": "chess"}]}
    w = World(*[reply] * 70)
    ctx = await w.ctx()
    assert await _svc(w).fill(ctx, FIELDS, "i like chess", "en") == {"likes": "chess"}
    assert "chess" in w.ai.calls[0]["user"]
    with pytest.raises(ConsentRequiredError):
        await _svc(w, consent=False).fill(ctx, FIELDS, "x", "en")
    with pytest.raises(ValidationFailedError):
        await _svc(w).fill(ctx, FIELDS, "   ", "en")
    with pytest.raises(ValidationFailedError):
        await _svc(w).fill(ctx, FIELDS + FIELDS[:1], "x", "en")
    svc = _svc(w)
    with pytest.raises(RateLimitedError):
        for _ in range(61):
            await svc.fill(ctx, FIELDS, "x", "en")


def test_future_interest_is_optional_and_reaches_the_model_and_search() -> None:
    assert clean_brief(**BRIEF).future_interest == ""
    brief = clean_brief(**BRIEF, future_interest="cybersecurity")
    assert brief.future_interest == "cybersecurity"
    assert "[future interest] cybersecurity" in brief_lines(brief, "en")
    assert all("cybersecurity" in q for q in search_queries(brief))
    with pytest.raises(ValidationFailedError):
        clean_brief(**BRIEF, future_interest="x" * 1501)


def test_project_prompt_crosses_interests() -> None:
    assert "Join two interests in one idea only when the join is natural" in (
        project_ideas.SYSTEM
    )
    assert "never glue unrelated interests together" in project_ideas.SYSTEM
    assert "[future interest]" in project_ideas.SYSTEM
