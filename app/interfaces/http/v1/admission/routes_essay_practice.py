"""Daily creative practice: today's theme, my entry, its evaluation, the history."""

import datetime as dt
from typing import Any, Literal

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_essays import Lang
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.essay_practice import PracticeToday
from app.modules.admission.domain.essay_flow import PRACTICE_MAX, PracticeEntry

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

PracticeKeyT = Literal["imagery", "voice", "structure", "originality"]


class PracticeScoreOut(BaseModel):
    """One creative-writing dimension, 0 to 5."""

    key: PracticeKeyT
    score: int
    comment: str


class PracticeEvaluationOut(BaseModel):
    """The coach's reading of one entry; never a rewrite."""

    summary: str
    scores: list[PracticeScoreOut]
    praise: list[str]
    try_next: list[str]
    idea_seeds: list[str]


class PracticeEntryOut(BaseModel):
    """One day's entry."""

    day: dt.date
    theme: str
    body: str
    word_count: int
    evaluation: PracticeEvaluationOut | None
    updated_at: dt.datetime | None


class PracticeTodayOut(BaseModel):
    """Today's theme (`theme` is a stable key, `prompt` its English text)."""

    day: dt.date
    theme: str
    prompt: str
    entry: PracticeEntryOut | None


class PracticeBodyIn(BaseModel):
    """The text of today's entry."""

    body: str = Field(max_length=PRACTICE_MAX)


class PracticeListOut(BaseModel):
    """My recent entries, newest first."""

    items: list[PracticeEntryOut]


def _entry(e: PracticeEntry) -> PracticeEntryOut:
    ev = e.evaluation
    return PracticeEntryOut(
        day=e.day,
        theme=e.theme,
        body=e.body,
        word_count=len(e.body.split()),
        evaluation=(
            None
            if ev is None
            else PracticeEvaluationOut(
                summary=ev.summary,
                scores=[
                    PracticeScoreOut(key=s.key, score=s.score, comment=s.comment)
                    for s in ev.scores
                ],
                praise=list(ev.praise),
                try_next=list(ev.try_next),
                idea_seeds=list(ev.idea_seeds),
            )
        ),
        updated_at=e.updated_at,
    )


def _today(t: PracticeToday) -> PracticeTodayOut:
    return PracticeTodayOut(
        day=t.day,
        theme=t.theme,
        prompt=t.prompt,
        entry=None if t.entry is None else _entry(t.entry),
    )


async def practice_today(container: ContainerDep, ctx: StudentCtx) -> PracticeTodayOut:
    """Today's theme and my entry for it, if I started one."""
    return _today(await container.admission.essay_practice.today(ctx))


async def practice_save(
    body: PracticeBodyIn, container: ContainerDep, ctx: StudentCtx
) -> PracticeTodayOut:
    """Write today's entry (sealed at rest); a changed text drops its evaluation."""
    return _today(await container.admission.essay_practice.save(ctx, body.body))


async def practice_evaluate(
    container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> PracticeTodayOut:
    """Evaluate today's entry (AI consent, daily limit); cached until it changes."""
    return _today(await container.admission.essay_practice.evaluate(ctx, _locale(lang)))


async def practice_history(container: ContainerDep, ctx: StudentCtx) -> PracticeListOut:
    """My recent entries, newest first."""
    rows = await container.admission.essay_practice.history(ctx)
    return PracticeListOut(items=[_entry(e) for e in rows])


def _route(path: str, endpoint: Any, method: str, op: str) -> None:
    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        operation_id=f"admission_essay_{op}",
        response_model=(
            PracticeListOut if op == "practice_history" else PracticeTodayOut
        ),
    )


_route("/essays/practice/today", practice_today, "GET", "practice_today")
_route("/essays/practice/today", practice_save, "PUT", "practice_save")
_route(
    "/essays/practice/today/evaluate", practice_evaluate, "POST", "practice_evaluate"
)
_route("/essays/practice", practice_history, "GET", "practice_history")
