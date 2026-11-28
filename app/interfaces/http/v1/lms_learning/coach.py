"""Routes of the Coach: learner sessions, solution keys (edit), insights (review)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.coach import (
    CoachReplyView,
    CoachTrigger,
    CoachTurnView,
    TutorSessionView,
)
from app.modules.lms.domain.learning.coach import (
    CoachOutcome,
    KeyStatus,
    Misconception,
    SolutionKey,
)
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]

router = APIRouter(prefix="/v1/lms", tags=["lms"])

MESSAGE_MAX = 2_000


class OpenSessionBody(BaseModel):
    """What opens the Coach."""

    block_id: str | None = Field(default=None, max_length=64)
    trigger: CoachTrigger


class TurnBody(BaseModel):
    """A message of the learner."""

    message: str = Field(min_length=1, max_length=MESSAGE_MAX)


class ExplainBody(BaseModel):
    """The answer the learner wants explained."""

    answer: str = Field(min_length=1, max_length=MESSAGE_MAX)


class CloseBody(BaseModel):
    """How the session ended."""

    outcome: CoachOutcome


class CloseOut(BaseModel):
    """The stored outcome."""

    outcome: CoachOutcome


class LatestSessionOut(BaseModel):
    """The newest session of the learner on a step with its messages."""

    session: TutorSessionView | None
    turns: list[CoachTurnView]


class MisconceptionDoc(BaseModel):
    """A typical mistake and the nudge for it."""

    pattern: str = Field(max_length=500)
    nudge: str = Field(max_length=500)


class SolutionKeyDoc(BaseModel):
    """The solution of one question as the teacher wrote it."""

    block_id: str = Field(max_length=64)
    question_id: str = Field(max_length=64)
    steps: list[str] = Field(default_factory=list, max_length=20)
    misconceptions: list[MisconceptionDoc] = Field(default_factory=list, max_length=20)
    status: KeyStatus = KeyStatus.DRAFT
    answers: list[str] = Field(default_factory=list, max_length=20)


class SolutionKeysDoc(BaseModel):
    """The keys of one step."""

    keys: list[SolutionKeyDoc] = Field(max_length=200)


class InsightRowOut(BaseModel):
    """Sessions of one step in the period."""

    step_id: UUID
    sessions: int
    resolved: int
    escalated: int
    max_hint_level: int


class InsightsOut(BaseModel):
    """The Coach sessions of a course by step."""

    steps: list[InsightRowOut]


def _keys_out(keys: list[SolutionKey]) -> SolutionKeysDoc:
    return SolutionKeysDoc(
        keys=[
            SolutionKeyDoc(
                block_id=k.block_id,
                question_id=k.question_id,
                steps=k.steps,
                misconceptions=[
                    MisconceptionDoc(pattern=m.pattern, nudge=m.nudge)
                    for m in k.misconceptions
                ],
                status=k.status,
                answers=k.answers,
            )
            for k in keys
        ]
    )


@router.post(
    "/steps/{step_id}/coach/sessions",
    operation_id="lms_open_coach_session",
    status_code=201,
)
async def open_coach_session(
    step_id: UUID,
    body: OpenSessionBody,
    response: Response,
    actor: ActorDep,
    container: ContainerDep,
) -> TutorSessionView:
    """Open a Coach session on a step the learner may read."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    return await container.lms.learning.open_coach.execute(
        actor, step_id, body.block_id, body.trigger
    )


@router.get("/steps/{step_id}/coach/sessions", operation_id="lms_latest_coach_session")
async def latest_coach_session(
    step_id: UUID,
    response: Response,
    actor: ActorDep,
    container: ContainerDep,
    latest: Annotated[int, Query(ge=0, le=1)] = 1,
) -> LatestSessionOut:
    """Return the learner's newest session on the step (`latest=1`)."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    found = await container.lms.learning.latest_coach.execute(actor, step_id)
    if found is None or not latest:
        return LatestSessionOut(session=None, turns=[])
    return LatestSessionOut(session=found.session, turns=found.turns)


@router.post("/coach/sessions/{session_id}/turns", operation_id="lms_coach_turn")
async def coach_turn(
    session_id: UUID,
    body: TurnBody,
    response: Response,
    actor: ActorDep,
    container: ContainerDep,
) -> CoachReplyView:
    """Send a message to the Coach; it hints and never gives the answer."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    try:
        return await container.lms.learning.coach_reply.execute(
            actor, session_id, body.message
        )
    except LookupError as error:
        raise NotFoundError(params={"session_id": str(session_id)}) from error


@router.post("/coach/sessions/{session_id}/hint", operation_id="lms_coach_hint")
async def coach_hint(
    session_id: UUID,
    response: Response,
    actor: ActorDep,
    container: ContainerDep,
) -> CoachReplyView:
    """Climb one rung of the hint ladder (three rungs at most)."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    try:
        return await container.lms.learning.coach_reply.hint(actor, session_id)
    except LookupError as error:
        raise NotFoundError(params={"session_id": str(session_id)}) from error


@router.post(
    "/coach/sessions/{session_id}/explain-mistake",
    operation_id="lms_coach_explain_mistake",
)
async def coach_explain_mistake(
    session_id: UUID,
    body: ExplainBody,
    response: Response,
    actor: ActorDep,
    container: ContainerDep,
) -> CoachReplyView:
    """Explain what is wrong in an answer without giving the solution."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    try:
        return await container.lms.learning.coach_reply.explain_mistake(
            actor, session_id, body.answer
        )
    except LookupError as error:
        raise NotFoundError(params={"session_id": str(session_id)}) from error


@router.post(
    "/coach/sessions/{session_id}/close", operation_id="lms_close_coach_session"
)
async def close_coach_session(
    session_id: UUID,
    body: CloseBody,
    response: Response,
    actor: ActorDep,
    container: ContainerDep,
) -> CloseOut:
    """Close the session once; a repeat returns the stored outcome."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    try:
        outcome = await container.lms.learning.close_coach.execute(
            actor, session_id, body.outcome
        )
    except LookupError as error:
        raise NotFoundError(params={"session_id": str(session_id)}) from error
    return CloseOut(outcome=outcome)


@router.get(
    "/courses/{course_id}/steps/{step_id}/solution-keys",
    operation_id="lms_get_solution_keys",
)
async def get_solution_keys(
    course_id: UUID, step_id: UUID, actor: ActorDep, container: ContainerDep
) -> SolutionKeysDoc:
    """Return the solution keys of the step (course staff with `edit`)."""
    found = await container.lms.learning.solution_keys.read(actor, course_id, step_id)
    return _keys_out(found.keys)


@router.put(
    "/courses/{course_id}/steps/{step_id}/solution-keys",
    operation_id="lms_put_solution_keys",
)
async def put_solution_keys(
    course_id: UUID,
    step_id: UUID,
    body: SolutionKeysDoc,
    actor: ActorDep,
    container: ContainerDep,
) -> SolutionKeysDoc:
    """Replace the solution keys of the step (course staff with `edit`)."""
    keys = [
        SolutionKey(
            step_id=step_id,
            block_id=k.block_id,
            question_id=k.question_id,
            steps=k.steps,
            misconceptions=[
                Misconception(m.pattern, m.nudge) for m in k.misconceptions
            ],
            status=k.status,
            answers=k.answers,
        )
        for k in body.keys
    ]
    found = await container.lms.learning.solution_keys.replace(
        actor, course_id, step_id, keys
    )
    return _keys_out(found.keys)


@router.get("/courses/{course_id}/coach/insights", operation_id="lms_coach_insights")
async def coach_insights(
    course_id: UUID,
    actor: ActorDep,
    container: ContainerDep,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> InsightsOut:
    """Return the Coach sessions by step (course staff with `review`)."""
    rows = await container.lms.learning.coach_insights.execute(
        actor, course_id, start, end
    )
    return InsightsOut(
        steps=[
            InsightRowOut(
                step_id=r.step_id,
                sessions=r.sessions,
                resolved=r.resolved,
                escalated=r.escalated,
                max_hint_level=r.max_hint_level,
            )
            for r in rows
        ]
    )
