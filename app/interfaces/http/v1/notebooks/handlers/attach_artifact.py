"""POST /v1/notebooks/{id}/artifacts/{aid}/attach-to-lesson."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    AttachArtifactBody,
    AttachedResourceResponse,
)
from app.modules.notebooks.domain.errors import FeatureDisabledError


async def attach_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    body: AttachArtifactBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> AttachedResourceResponse:
    """Render a report, table or slides as a file and add it to the teacher's lesson."""
    use_case = notebooks.attach_artifact
    if use_case is None:
        raise FeatureDisabledError(params={"feature": "lesson-attach"})
    ref = await use_case.execute(
        actor, notebook_id, artifact_id, body.lesson_id, body.role
    )
    return AttachedResourceResponse(
        link_id=ref.link_id,
        lesson_id=ref.lesson_id,
        title=ref.title,
        short_url=ref.short_url,
    )
