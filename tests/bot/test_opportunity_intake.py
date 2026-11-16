"""The /event intake: research, missing-field questions, confirm and submit."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.bot.routers.admission_intake import IntakeCb
from app.interfaces.bot.utilities.commands import command_names_for
from app.modules.admission.application.opportunity_intake import (
    OpportunityIntake,
    build_intake_fetcher,
)
from app.modules.admission.domain.opportunities import OpportunityDraft
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG
from tests.bot.support.harness import Harness

import pytest

MATH = UUID("01900000-0000-7000-8000-000000000001")
TAXONOMY = [
    SimpleNamespace(
        id=UUID(int=1),
        name={"en": "Science"},
        subfields=[
            SimpleNamespace(
                id=UUID(int=2),
                name={"en": "Natural"},
                subjects=[SimpleNamespace(id=MATH, name={"en": "Mathematics"})],
            )
        ],
    )
]


class FakeAi:
    def __init__(self) -> None:
        self.calls = 0

    async def json(self, **_: Any) -> tuple[dict[str, Any], None]:
        self.calls += 1
        return {
            "title": "",
            "summary": "A city olympiad.",
            "provider": "City",
            "kind": "event",
            "registration_deadlines": [],
            "event_dates": [],
            "recurrence": "",
            "subject_ids": [],
            "main_url": "https://olymp.example/x",
            "materials": [],
            "uncertain": ["kind"],
        }, None


class FakePrompts:
    async def text(self, *_: Any) -> str:
        return "system"


class Fetcher:
    def __init__(self) -> None:
        self.real, self.fetched = build_intake_fetcher(), list[str]()

    def check(self, url: str) -> None:
        self.real.check(url)

    async def fetch(self, url: str) -> Any:
        self.fetched.append(url)
        return SimpleNamespace(data=b"<p>City olympiad</p>")


class Opportunities:
    def __init__(self) -> None:
        self.submitted: list[OpportunityDraft] = []

    async def taxonomy(self) -> list[Any]:
        return TAXONOMY

    async def submit(self, ctx: Any, draft: OpportunityDraft, **_: Any) -> None:
        self.submitted.append(draft)


def install(harness: Harness, *, staff: bool) -> tuple[FakeAi, Fetcher, Opportunities]:
    ai, fetcher, opportunities = FakeAi(), Fetcher(), Opportunities()

    async def execute(actor: Any) -> Any:
        return SimpleNamespace(
            actor=actor,
            admission=SimpleNamespace(
                is_staff=staff, has_help_grants=False, blocked=False
            ),
        )

    harness.world.container.admission = SimpleNamespace(
        actor=SimpleNamespace(execute=execute),
        opportunities=opportunities,
        opportunity_intake=OpportunityIntake(
            ai, FakePrompts(), fetcher=fetcher  # type: ignore[arg-type]
        ),
    )
    return ai, fetcher, opportunities


async def test_post_to_questions_to_confirmed_submission(harness: Harness) -> None:
    ai, fetcher, opportunities = install(harness, staff=True)
    await harness.send("/event", user_id=TEACHER_TG)
    assert "bot-intake-ask-post" in harness.last_text()
    await harness.send(
        "Olympiad https://olymp.example/x http://127.0.0.1/secret",
        user_id=TEACHER_TG,
    )
    assert fetcher.fetched == ["https://olymp.example/x"]  # the blocked one is not
    assert "bot-intake-ask-title" in harness.last_text()
    await harness.send("City <b>math</b> olympiad", user_id=TEACHER_TG)
    assert "bot-intake-ask-kind" in harness.last_text()
    await harness.send("an exam I think", user_id=TEACHER_TG)  # typed, not pressed
    assert "bot-intake-use-buttons" in harness.last_text()
    assert ai.calls == 1  # the assistant did not take the text
    assert await harness.state_of(TEACHER_TG) is not None
    await harness.press(IntakeCb(a="k", v=0).pack(), user_id=TEACHER_TG)
    assert "bot-intake-ask-dates" in harness.last_text()
    await harness.send("nope", user_id=TEACHER_TG)
    assert "bot-intake-bad-date" in harness.last_text()
    await harness.send("2027-03-15", user_id=TEACHER_TG)
    assert "bot-intake-ask-deadline" in harness.last_text()
    await harness.press(IntakeCb(a="sk").pack(), user_id=TEACHER_TG)
    assert "bot-intake-ask-subjects" in harness.last_text()
    await harness.press(IntakeCb(a="s", v=0).pack(), user_id=TEACHER_TG)
    await harness.press(IntakeCb(a="sd").pack(), user_id=TEACHER_TG)
    summary = harness.last_text()
    assert "bot-intake-summary-title" in summary
    assert "&lt;b&gt;math&lt;/b&gt;" in summary  # typed text is escaped
    assert all(len(c.encode()) <= 64 for c in harness.last_callbacks())
    await harness.press(IntakeCb(a="ok").pack(), user_id=TEACHER_TG)
    assert "bot-intake-submitted" in harness.last_text()
    (draft,) = opportunities.submitted
    assert draft.title == "City <b>math</b> olympiad"
    assert draft.subject_ids == (MATH,)
    assert [d.isoformat() for d in draft.exam_dates] == ["2027-03-15"]
    assert draft.url == "https://olymp.example/x"
    assert ai.calls == 1
    assert await harness.state_of(TEACHER_TG) is None


async def test_non_staff_are_refused(harness: Harness) -> None:
    ai, fetcher, opportunities = install(harness, staff=False)
    await harness.send("/event https://olymp.example/x", user_id=TEACHER_TG)
    assert "bot-intake-forbidden" in harness.last_text()
    await harness.press(IntakeCb(a="ok").pack(), user_id=TEACHER_TG)
    assert ai.calls == 0 and fetcher.fetched == [] and opportunities.submitted == []


async def test_student_submits_through_the_same_flow(harness: Harness) -> None:
    ai, fetcher, opportunities = install(harness, staff=False)
    await harness.send("/event", user_id=STUDENT_TG)
    assert "bot-intake-ask-post" in harness.last_text()
    await harness.send("Olympiad https://olymp.example/x", user_id=STUDENT_TG)
    await harness.send("City math olympiad", user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="k", v=0).pack(), user_id=STUDENT_TG)
    await harness.send("2027-03-15", user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="sk").pack(), user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="s", v=0).pack(), user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="sd").pack(), user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="ok").pack(), user_id=STUDENT_TG)
    assert "bot-intake-submitted" in harness.last_text()
    assert [d.title for d in opportunities.submitted] == ["City math olympiad"]


async def test_rate_limited_student_is_told_so(harness: Harness) -> None:
    _, _, opportunities = install(harness, staff=False)

    async def limited(*_: Any, **__: Any) -> None:
        raise RateLimitedError(params={"retry_after": 60})

    opportunities.submit = limited  # type: ignore[method-assign]
    await harness.send("/event", user_id=STUDENT_TG)
    await harness.send("Olympiad https://olymp.example/x", user_id=STUDENT_TG)
    await harness.send("City math olympiad", user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="k", v=0).pack(), user_id=STUDENT_TG)
    await harness.send("2027-03-15", user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="sk").pack(), user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="s", v=0).pack(), user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="sd").pack(), user_id=STUDENT_TG)
    await harness.press(IntakeCb(a="ok").pack(), user_id=STUDENT_TG)
    assert "bot-intake-rate-limited" in harness.last_text()


def test_event_command_is_listed_for_students_and_admission_staff() -> None:
    assert "event" in command_names_for([Role.COUNSELOR])
    assert "event" in command_names_for([Role.TEACHER, Role.MENTOR])
    assert "event" in command_names_for([Role.STUDENT])
    assert "event" not in command_names_for([Role.TEACHER])


@pytest.mark.parametrize("locale", ["uz", "ru", "en"])
def test_event_command_description_exists_in_every_locale(locale: str) -> None:
    path = Path(__file__).parents[2] / "locales" / locale / "bot.json"
    texts = json.loads(path.read_text(encoding="utf-8"))
    assert texts["bot-command-event"].strip()
    assert texts["bot-intake-rate-limited"].strip()
