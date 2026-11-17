"""Admission assistant: starter questions for the current screen.

The conversation itself is an AI chat with assistant `admission`
(`/v1/ai/chats`); its tools read the applicant's own application.
"""

from typing import Annotated, Any

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.domain.assistant import SCREEN_PATH_MAX

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Lang = Annotated[str | None, Header(alias="Accept-Language")]


class SuggestionsOut(BaseModel):
    """Starter questions for one screen."""

    items: list[str]


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


_route(
    "/assistant/suggestions",
    suggestions,
    "GET",
    "assistant_suggestions",
    response_model=SuggestionsOut,
)
