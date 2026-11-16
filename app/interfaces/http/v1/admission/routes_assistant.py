"""Admission assistant: answers about the student's own data and current screen.

Only the applicant may use it. `POST /assistant/messages` runs the model with
read-only tools; cards it returns (open a page, propose a task) change nothing.
"""

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.domain.assistant import (
    MESSAGE_MAX,
    SCREEN_PATH_MAX,
    SCREEN_SUMMARY_MAX,
    SCREEN_TITLE_MAX,
    Action,
    Citation,
    Screen,
)

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Lang = Annotated[str | None, Header(alias="Accept-Language")]


class ScreenIn(BaseModel):
    """What the page showed when the student asked."""

    path: str = Field(max_length=SCREEN_PATH_MAX)
    title: str = Field(max_length=SCREEN_TITLE_MAX)
    summary: str = Field(max_length=SCREEN_SUMMARY_MAX)


class MessageIn(BaseModel):
    """A question; without `thread_id` a new thread starts."""

    thread_id: UUID | None = None
    message: str = Field(min_length=1, max_length=MESSAGE_MAX)
    screen: ScreenIn | None = None


class CitationOut(BaseModel):
    """A record of the student's data the answer relied on."""

    source: str
    title: str
    url_path: str


class ProposedTaskOut(BaseModel):
    """A task draft; the student decides whether to create it."""

    title: str
    description: str
    due_on: dt.date | None


class ActionOut(BaseModel):
    """A button: `open` a page or `propose_task`."""

    kind: Literal["open", "propose_task"]
    label: str
    url_path: str | None = None
    task: ProposedTaskOut | None = None


class ReplyOut(BaseModel):
    """The answer (markdown) with its sources and buttons."""

    thread_id: UUID
    message_id: UUID
    reply: str
    citations: list[CitationOut]
    actions: list[ActionOut]


class ThreadOut(BaseModel):
    """A thread in the list."""

    id: UUID
    title: str
    updated_at: dt.datetime


class ThreadsOut(BaseModel):
    """The student's threads, latest first."""

    items: list[ThreadOut]


class MessageOut(BaseModel):
    """One stored message."""

    id: UUID
    role: Literal["user", "assistant"]
    text: str
    citations: list[CitationOut]
    actions: list[ActionOut]
    created_at: dt.datetime


class ThreadDetailOut(BaseModel):
    """A thread with its messages."""

    id: UUID
    title: str
    messages: list[MessageOut]


class SuggestionsOut(BaseModel):
    """Starter questions for a screen."""

    items: list[str]


def _citation(c: Citation) -> CitationOut:
    return CitationOut(source=c.source, title=c.title, url_path=c.url_path)


def _action(a: Action) -> ActionOut:
    task = None
    if a.task:
        due = a.task.get("due_on")
        task = ProposedTaskOut(
            title=a.task.get("title", ""),
            description=a.task.get("description", ""),
            due_on=dt.date.fromisoformat(due) if due else None,
        )
    return ActionOut(kind=a.kind, label=a.label, url_path=a.url_path, task=task)


async def send(
    body: MessageIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> ReplyOut:
    """Ask the assistant; needs the `admission_ai` consent."""
    screen = (
        Screen(body.screen.path, body.screen.title, body.screen.summary)
        if body.screen
        else None
    )
    reply = await container.admission.assistant.send(
        ctx, body.thread_id, body.message, screen, _locale(accept_language)
    )
    return ReplyOut(
        thread_id=reply.thread_id,
        message_id=reply.message_id,
        reply=reply.text,
        citations=[_citation(c) for c in reply.citations],
        actions=[_action(a) for a in reply.actions],
    )


async def list_threads(container: ContainerDep, ctx: AdmissionCtx) -> ThreadsOut:
    """My conversations, latest first."""
    rows = await container.admission.assistant.threads(ctx)
    return ThreadsOut(
        items=[ThreadOut(id=t.id, title=t.title, updated_at=t.updated_at) for t in rows]
    )


async def get_thread(
    thread_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ThreadDetailOut:
    """One of my conversations with its messages."""
    thread, messages = await container.admission.assistant.thread(ctx, thread_id)
    return ThreadDetailOut(
        id=thread.id,
        title=thread.title,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                text=m.text,
                citations=[_citation(c) for c in m.citations],
                actions=[_action(a) for a in m.actions],
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


async def delete_thread(
    thread_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Delete one of my conversations."""
    await container.admission.assistant.delete(ctx, thread_id)
    return Response(status_code=204)


async def suggestions(
    container: ContainerDep,
    ctx: AdmissionCtx,
    path: Annotated[str, Query(max_length=SCREEN_PATH_MAX)] = "/",
    accept_language: Lang = None,
) -> SuggestionsOut:
    """Three starter questions for the screen at `path`."""
    del ctx
    items = container.admission.assistant.suggestions(path, _locale(accept_language))
    return SuggestionsOut(items=items)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_route("/assistant/messages", send, "POST", "assistant_send", response_model=ReplyOut)
_route(
    "/assistant/threads",
    list_threads,
    "GET",
    "assistant_threads",
    response_model=ThreadsOut,
)
_route(
    "/assistant/threads/{thread_id}",
    get_thread,
    "GET",
    "assistant_thread",
    response_model=ThreadDetailOut,
)
_route(
    "/assistant/threads/{thread_id}",
    delete_thread,
    "DELETE",
    "assistant_thread_delete",
    status_code=204,
)
_route(
    "/assistant/suggestions",
    suggestions,
    "GET",
    "assistant_suggestions",
    response_model=SuggestionsOut,
)
