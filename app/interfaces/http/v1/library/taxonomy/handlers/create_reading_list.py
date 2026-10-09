"""POST /v1/library/reading-lists."""

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, TeachingActor
from app.interfaces.http.v1.library.taxonomy.schemas_lists import (
    CreateReadingListBody,
    ReadingListDetailResponse,
)


async def create_reading_list(
    body: CreateReadingListBody,
    library: Library,
    actor: TeachingActor,
    accept_language: AcceptLanguage = None,
) -> ReadingListDetailResponse:
    """Create a list (teachers for their subjects and groups, librarians for any)."""
    view = await library.taxonomy.create_reading_list.execute(
        actor,
        title=body.title,
        scope=body.scope,
        description=body.description,
        subject_id=body.subject_id,
        group_ids=body.group_ids,
        year_of_study=body.year_of_study,
        academic_year=body.academic_year,
        term_half=body.term_half,
        status=body.status,
        accept_language=accept_language,
    )
    return ReadingListDetailResponse.from_detail(view)
