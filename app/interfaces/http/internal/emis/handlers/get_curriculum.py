"""GET /internal/emis/{user_id}/curriculum."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisCurriculumResponse

from fastapi import Depends


async def get_curriculum(
    user_id: UUID, container: Annotated[Container, Depends(get_container)]
) -> EmisCurriculumResponse:
    """Return the student's whole curriculum: semesters, hours per subject, exams."""
    curriculum = await container.identity.emis.gateway.curriculum(user_id)
    return EmisCurriculumResponse.from_contract(curriculum)
