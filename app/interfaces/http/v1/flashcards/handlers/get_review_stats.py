"""GET /v1/me/flashcard-sets/stats."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.flashcards.schemas import (
    STATS_YEAR_MAX,
    STATS_YEAR_MIN,
    ReviewStatsResponse,
)

from fastapi import Query


async def get_review_stats(
    container: ContainerDep,
    actor: StudentActor,
    set_id: UUID | None = None,
    year: Annotated[int | None, Query(ge=STATS_YEAR_MIN, le=STATS_YEAR_MAX)] = None,
) -> ReviewStatsResponse:
    """Return the review heatmap and streaks of one set or of all sets."""
    view = await container.flashcards.get_review_stats.execute(
        owner_id=actor.user_id, set_id=set_id, year=year
    )
    return ReviewStatsResponse.from_view(view)
