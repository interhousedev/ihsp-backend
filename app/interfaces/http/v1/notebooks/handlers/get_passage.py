"""GET /v1/notebooks/{id}/passages/{pid}."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_sources import PassageDetailResponse
from app.modules.notebooks.application.get_passage import CONTEXT_MAX

from fastapi import Query

CONTEXT_DEFAULT = 2


async def get_passage(
    notebook_id: UUID,
    passage_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
    context: Annotated[int, Query(ge=0, le=CONTEXT_MAX)] = CONTEXT_DEFAULT,
) -> PassageDetailResponse:
    """Return a passage with its source and `context` passages on each side."""
    view = await notebooks.get_passage.execute(
        actor, notebook_id, passage_id, context=context
    )
    return PassageDetailResponse.from_view(view)
