"""The opportunity intake: links, the SSRF policy, the model output and access."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

from app.modules.admission.application.opportunity_intake import (
    IntakeDraft,
    OpportunityIntake,
    build_intake_fetcher,
    clean,
    extract_links,
    missing_fields,
    research_url,
)
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.shared.actor import Role
from app.shared.ai_tasks import AiTask

import pytest

TODAY = dt.date(2026, 9, 1)
TAXONOMY = [
    SimpleNamespace(
        id="f1",
        name={"en": "Science"},
        subfields=[
            SimpleNamespace(
                id="sf1",
                name={"en": "Natural"},
                subjects=[SimpleNamespace(id="math", name={"en": "Mathematics"})],
            )
        ],
    )
]


def ctx(
    *,
    staff: bool = True,
    helper: bool = False,
    blocked: bool = False,
    student: bool = False,
) -> Any:
    roles = frozenset({Role.STUDENT}) if student else frozenset()
    return SimpleNamespace(
        actor=SimpleNamespace(roles=roles),
        admission=SimpleNamespace(
            is_staff=staff, has_help_grants=helper, blocked=blocked
        ),
    )


class FakeAi:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data, self.calls = data, list[dict[str, Any]]()

    async def json(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
        self.calls.append(kwargs)
        return self.data, ""


class FakePrompts:
    async def text(self, task: AiTask, slot: str, locale: str) -> str:
        return "system"


class RecordingFetcher:
    """The real SSRF check; fetches are recorded and answered locally."""

    def __init__(self) -> None:
        self.real, self.fetched = build_intake_fetcher(), list[str]()

    def check(self, url: str) -> None:
        self.real.check(url)

    async def fetch(self, url: str) -> Any:
        self.fetched.append(url)
        return SimpleNamespace(data=b"<p>Olympiad on 2026-10-10</p>")


def answer(**over: Any) -> dict[str, Any]:
    base = {
        "title": "Math olympiad",
        "summary": "A city olympiad.",
        "provider": "City",
        "kind": "event",
        "registration_deadlines": ["2026-09-20"],
        "event_dates": ["2026-10-10"],
        "recurrence": "",
        "subject_ids": ["math", "ghost"],
        "main_url": "https://evil.example/not-in-text",
        "materials": [],
        "uncertain": [],
    }
    return {**base, **over}


async def test_blocked_urls_are_never_fetched_and_telegram_uses_the_preview() -> None:
    ai = FakeAi(answer(main_url="http://127.0.0.1/admin"))
    fetcher: Any = RecordingFetcher()
    intake = OpportunityIntake(ai, FakePrompts(), fetcher=fetcher)
    text = (
        "Olympiad! http://127.0.0.1/admin https://localhost/x "
        "https://t.me/c/123/4 https://t.me/olymp/77"
    )
    draft = await intake.research(
        ctx(), text, locale="en", today=TODAY, taxonomy=TAXONOMY
    )
    assert fetcher.fetched == ["https://t.me/s/olymp/77"]
    assert set(draft.blocked) == {
        "http://127.0.0.1/admin",
        "https://localhost/x",
        "https://t.me/c/123/4",
    }
    assert draft.url in {"https://t.me/olymp/77", "https://t.me/s/olymp/77"}
    assert draft.subject_ids == ["math"]
    assert "<event_text>" in ai.calls[0]["user"]


async def test_helpers_may_research_and_others_are_refused() -> None:
    fetcher: Any = RecordingFetcher()
    intake = OpportunityIntake(FakeAi(answer()), FakePrompts(), fetcher=fetcher)
    draft = await intake.research(
        ctx(staff=False, helper=True), "Olympiad", locale="en", today=TODAY, taxonomy=[]
    )
    assert draft.title == "Math olympiad"
    for denied in (ctx(staff=False), ctx(blocked=True)):
        with pytest.raises(AdmissionForbiddenError):
            await intake.research(
                denied, "Olympiad", locale="en", today=TODAY, taxonomy=[]
            )


async def test_students_may_research() -> None:
    fetcher: Any = RecordingFetcher()
    intake = OpportunityIntake(FakeAi(answer()), FakePrompts(), fetcher=fetcher)
    draft = await intake.research(
        ctx(staff=False, student=True),
        "Olympiad",
        locale="en",
        today=TODAY,
        taxonomy=[],
    )
    assert draft.title == "Math olympiad"


def test_clean_drops_unknown_values_and_lists_missing_fields() -> None:
    draft = clean(
        answer(
            title="",
            kind="party",
            event_dates=["2040-01-01", "soon"],
            registration_deadlines=[],
            recurrence="FREQ=SECONDLY",
            materials=[{"title": "Rules", "url": "https://a.uz/rules"}],
        ),
        known={"https://a.uz/rules"},
        subjects={"math"},
        today=TODAY,
    )
    assert draft.kind == "event" and draft.recurrence == "" and draft.event_dates == []
    assert draft.url == "https://a.uz/rules" and draft.materials == []
    assert draft.missing[:3] == ["title", "kind", "dates"]


def test_missing_fields_of_a_recurring_draft() -> None:
    draft = IntakeDraft(title="SAT", kind="recurring", subject_ids=["math"])
    assert missing_fields(draft) == ["recurrence"]


def test_links_and_research_targets() -> None:
    assert extract_links("see https://a.uz/x, and https://a.uz/x.") == [
        "https://a.uz/x"
    ]
    assert research_url("https://t.me/joinchat/abc") is None
    assert research_url("https://a.uz/x") == "https://a.uz/x"
