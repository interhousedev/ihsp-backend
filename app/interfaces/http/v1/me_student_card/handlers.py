"""Handlers of the student's own card."""

from dataclasses import asdict
from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_student_card.schemas import (
    GoogleWalletLinkResponse,
    StudentCardResponse,
    StudentCardTokenResponse,
)
from app.modules.identity.domain.student_card import StudentCard
from app.shared.actor import Actor, Role

from fastapi import Depends, Response

StudentActor = Annotated[Actor, Depends(require_roles(Role.STUDENT))]
ContainerDep = Annotated[Container, Depends(get_container)]


def card_fields(card: StudentCard) -> dict[str, Any]:
    """The card as response fields, with the full name."""
    return {**asdict(card), "full_name": card.full_name}


async def get_student_card(
    actor: StudentActor, container: ContainerDep
) -> StudentCardResponse:
    """Return the caller's student card and its QR token."""
    own = await container.student_card.card(actor.user_id)
    return StudentCardResponse.model_validate(
        {
            **card_fields(own.card),
            "qr_token": own.qr_token,
            "wallet": asdict(own.wallet),
        }
    )


async def regenerate_student_card_token(
    actor: StudentActor, container: ContainerDep
) -> StudentCardTokenResponse:
    """Replace the QR token; the printed or shared old code stops working."""
    token = await container.student_card.regenerate(actor.user_id)
    return StudentCardTokenResponse(token=token)


async def get_student_card_apple_pass(
    actor: StudentActor, container: ContainerDep
) -> Response:
    """Return the signed Apple Wallet pass; 404 when Apple Wallet is off."""
    data = await container.student_card.apple_pass(actor.user_id)
    return Response(
        content=data,
        media_type="application/vnd.apple.pkpass",
        headers={
            "Content-Disposition": 'attachment; filename="student-card.pkpass"',
            "Cache-Control": "no-store",
        },
    )


async def get_student_card_google_link(
    actor: StudentActor, container: ContainerDep
) -> GoogleWalletLinkResponse:
    """Return the "Add to Google Wallet" link; 404 when Google Wallet is off."""
    url = await container.student_card.google_save_url(actor.user_id)
    return GoogleWalletLinkResponse(url=url)
