"""GET /v1/library/book-plans?subject_id&year_of_study."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, TeachingActor
from app.interfaces.http.v1.library.reader.schemas_plans import BookPlanResponse

from fastapi import Query


async def get_book_plan(
    library: Library,
    actor: TeachingActor,
    subject_id: UUID,
    year_of_study: Annotated[int, Query(ge=1, le=4)],
) -> BookPlanResponse | None:
    """The textbook plan of the subject and year (`null` when there is none)."""
    view = await library.reader.get_book_plan.execute(
        actor, subject_id=subject_id, year_of_study=year_of_study
    )
    return BookPlanResponse.from_view(view) if view else None
