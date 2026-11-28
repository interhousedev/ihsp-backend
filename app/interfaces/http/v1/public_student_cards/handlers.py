"""Handlers of the public student card (no sign-in, the token is the proof)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.me_student_card.handlers import card_fields
from app.interfaces.http.v1.me_student_card.schemas import PublicStudentCardResponse

from fastapi import Depends, Response

ContainerDep = Annotated[Container, Depends(get_container)]
ClientIp = Annotated[str | None, Depends(get_client_ip)]


async def get_public_student_card(
    token: str, container: ContainerDep, client_ip: ClientIp
) -> PublicStudentCardResponse:
    """Return the card behind a token; 404 when it is unknown or was replaced."""
    card = await container.student_card.lookup(token, client_ip)
    return PublicStudentCardResponse.model_validate(card_fields(card))


async def get_public_student_card_photo(
    token: str, container: ContainerDep, client_ip: ClientIp
) -> Response:
    """Return the photo behind a token; 404 when none or hidden from the public."""
    photo = await container.student_card.photo(token, client_ip)
    return Response(
        content=photo.data,
        media_type=photo.content_type,
        headers={"Cache-Control": "no-store"},
    )
