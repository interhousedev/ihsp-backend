"""GET /internal/emis/{user_id}/certificates."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisCertificateResponse

from fastapi import Depends


async def get_certificates(
    user_id: UUID, container: Annotated[Container, Depends(get_container)]
) -> list[EmisCertificateResponse]:
    """Return the CEFR and national certificates of the student's EMIS profile."""
    found = await container.identity.emis.gateway.certificates(user_id)
    return [EmisCertificateResponse.from_contract(item) for item in found]
