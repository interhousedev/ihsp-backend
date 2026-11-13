"""Handlers of the student's own card."""

from dataclasses import asdict
from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_student_card.schemas import (
    StudentCardResponse,
    StudentCardTokenResponse,
)
from app.shared.actor import Actor, Role

from fastapi import Depends

StudentActor = Annotated[Actor, Depends(require_roles(Role.STUDENT))]
ContainerDep = Annotated[Container, Depends(get_container)]


async def get_student_card(
    actor: StudentActor, container: ContainerDep
) -> StudentCardResponse:
    """Return the caller's student card."""
    card = await container.student_card.card(actor.user_id)
    return StudentCardResponse.model_validate(asdict(card))


async def issue_student_card_token(
    actor: StudentActor, container: ContainerDep
) -> StudentCardTokenResponse:
    """Issue a two-minute token that shows the card to a verifier."""
    issued = await container.student_card.issue(actor.user_id)
    return StudentCardTokenResponse.model_validate(asdict(issued))
