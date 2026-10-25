"""PUT /v1/library/book-plans."""

from app.interfaces.http.v1.library.deps import Library, TeachingActor
from app.interfaces.http.v1.library.reader.schemas_plans import (
    BookPlanResponse,
    PutBookPlanBody,
)


async def put_book_plan(
    body: PutBookPlanBody, library: Library, actor: TeachingActor
) -> BookPlanResponse:
    """Save the plan (teachers of the subject and librarians)."""
    view = await library.reader.put_book_plan.execute(
        actor,
        subject_id=body.subject_id,
        year_of_study=body.year_of_study,
        item_id=body.item_id,
        sections=[section.to_section() for section in body.sections],
    )
    return BookPlanResponse.from_view(view)
