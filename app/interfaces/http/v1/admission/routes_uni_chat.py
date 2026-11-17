"""University chats: one smart AI chat per target university.

The conversation itself runs through `/v1/ai/chats/{chat_id}/messages`; these
routes open the chat, keep the default prompt and run it.
"""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.interfaces.http.v1.ai.handlers.send_message import stream_turn
from app.interfaces.http.v1.ai.schemas import TurnResultResponse
from app.interfaces.http.v1.notebooks.handlers.sse import wants_stream
from app.modules.admission.domain.uni_chat import PROMPT_LIMIT

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Lang = Annotated[str | None, Header(alias="Accept-Language")]


class UniChatOut(BaseModel):
    """The student's chat of one university."""

    chat_id: UUID
    institution_id: UUID
    created: bool
    auto_run_pending: bool
    has_default_prompt: bool


class DefaultPromptIn(BaseModel):
    """The prompt sent when a university chat opens ("" removes it)."""

    prompt: str = Field(max_length=PROMPT_LIMIT)


class DefaultPromptOut(BaseModel):
    """The student's default prompt, if any."""

    prompt: str | None


class AdviceItemOut(BaseModel):
    """A titled suggestion."""

    title: str
    detail: str


class UniChatSuggestionsOut(BaseModel):
    """Questions, academic and activity advice for one university."""

    questions: list[str]
    academic: list[AdviceItemOut]
    activities: list[AdviceItemOut]


async def open_chat(
    institution_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> UniChatOut:
    """Return the chat of the university, creating it on the first open."""
    opened = await container.admission.uni_chat.open(ctx, institution_id)
    return UniChatOut(
        chat_id=opened.chat_id,
        institution_id=opened.institution_id,
        created=opened.created,
        auto_run_pending=opened.auto_run_pending,
        has_default_prompt=opened.default_prompt is not None,
    )


async def get_default_prompt(
    container: ContainerDep, ctx: AdmissionCtx
) -> DefaultPromptOut:
    """Return the default prompt."""
    return DefaultPromptOut(
        prompt=await container.admission.uni_chat.default_prompt(ctx)
    )


async def put_default_prompt(
    body: DefaultPromptIn, container: ContainerDep, ctx: AdmissionCtx
) -> DefaultPromptOut:
    """Store the default prompt; an empty one removes it."""
    prompt = await container.admission.uni_chat.set_default_prompt(ctx, body.prompt)
    return DefaultPromptOut(prompt=prompt)


async def run_default(
    institution_id: UUID,
    request: Request,
    container: ContainerDep,
    ctx: AdmissionCtx,
    auto: Annotated[bool, Query()] = False,
    accept_language: Lang = None,
) -> Any:
    """Send the default prompt with web search; `auto` runs only once (204 after).

    With `Accept: text/event-stream` the turn streams like a chat message.
    """
    run = await container.admission.uni_chat.claim_run(
        ctx, institution_id, auto=auto, locale=_locale(accept_language)
    )
    if run is None:
        return Response(status_code=204)
    use_case = container.ai.send_message
    if wants_stream(request):
        events = use_case.stream(
            actor=ctx.actor,
            chat_id=run.chat_id,
            text=run.prompt,
            command=None,
            args="",
            file_ids=[],
            web_search=True,
        )
        return await stream_turn(events)
    view = await use_case.execute(
        actor=ctx.actor,
        chat_id=run.chat_id,
        text=run.prompt,
        command=None,
        args="",
        file_ids=[],
        web_search=True,
    )
    return TurnResultResponse.from_view(view)


async def suggestions(
    institution_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> UniChatSuggestionsOut:
    """Advice for the student about the university (cached, AI-limited)."""
    advice = await container.admission.uni_advice.advice(
        ctx, institution_id, _locale(accept_language)
    )
    return UniChatSuggestionsOut(
        questions=advice.questions,
        academic=[
            AdviceItemOut(title=a.title, detail=a.detail) for a in advice.academic
        ],
        activities=[
            AdviceItemOut(title=a.title, detail=a.detail) for a in advice.activities
        ],
    )


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_route(
    "/uni-chats/{institution_id}",
    open_chat,
    "POST",
    "uni_chat_open",
    response_model=UniChatOut,
)
_route(
    "/uni-chat/default-prompt",
    get_default_prompt,
    "GET",
    "uni_chat_default_prompt_get",
    response_model=DefaultPromptOut,
)
_route(
    "/uni-chat/default-prompt",
    put_default_prompt,
    "PUT",
    "uni_chat_default_prompt_put",
    response_model=DefaultPromptOut,
)
_route(
    "/uni-chats/{institution_id}/run-default",
    run_default,
    "POST",
    "uni_chat_run_default",
    response_model=TurnResultResponse,
    responses={204: {"description": "Already auto-run; nothing sent"}},
)
_route(
    "/uni-chats/{institution_id}/suggestions",
    suggestions,
    "GET",
    "uni_chat_suggestions",
    response_model=UniChatSuggestionsOut,
)
