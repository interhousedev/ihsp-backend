"""GET /v1/library/my-groups."""

from app.interfaces.http.v1.library.deps import Library, TeachingActor
from app.interfaces.http.v1.library.taxonomy.schemas_groups import GroupResponse


async def list_my_groups(library: Library, actor: TeachingActor) -> list[GroupResponse]:
    """Groups the teacher teaches or curates; librarians and Administration get all."""
    groups = await library.taxonomy.list_my_groups.execute(actor)
    return [GroupResponse.from_view(group) for group in groups]
