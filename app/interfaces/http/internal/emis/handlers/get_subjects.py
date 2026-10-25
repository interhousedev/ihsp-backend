"""GET /internal/emis/{user_id}/subjects."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisSubjectResponse

from fastapi import Depends


async def get_subjects(
    user_id: UUID, container: Annotated[Container, Depends(get_container)]
) -> list[EmisSubjectResponse]:
    """Return the subjects of the student's curriculum."""
    subjects = await container.identity.emis.gateway.subjects(user_id)
    return [EmisSubjectResponse.from_contract(subject) for subject in subjects]
