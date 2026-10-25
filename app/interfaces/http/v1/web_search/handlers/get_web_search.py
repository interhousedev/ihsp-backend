"""GET /v1/ai/web-search."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.web_search.schemas import WebQuotaResponse
from app.shared.actor import Actor

from fastapi import Depends


async def get_web_search(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> WebQuotaResponse:
    """Whether web search is on for the caller and how many searches are left today."""
    quota = await container.ai.web_search.quota(actor)
    return WebQuotaResponse.from_quota(quota)
