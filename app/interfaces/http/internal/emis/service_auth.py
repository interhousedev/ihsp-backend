"""Authentication of internal callers by the shared service token."""

import hmac
from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.shared.base_error import UnauthorizedError

from fastapi import Depends, Request


async def require_service_token(
    request: Request, container: Annotated[Container, Depends(get_container)]
) -> None:
    """Accept ``Authorization: Bearer <TOKENS__SERVICE_TOKEN>`` and nothing else."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    expected = container.settings.tokens.service_token.get_secret_value()
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.strip().encode(), expected.encode()
    ):
        raise UnauthorizedError(support_details="invalid service token")
