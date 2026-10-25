"""POST /v1/public/reports."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.links.public_shares.schemas import ReportBody
from app.modules.links.domain.report_reason import ReportReason

from fastapi import Depends, Request, Response


async def report_link(
    body: ReportBody,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> Response:
    """Report a public page; Administration reviews it (SL-9, UF-PUB-05)."""
    await container.links.report_link.execute(
        body.slug,
        ReportReason(body.reason),
        body.comment,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return Response(status_code=202)
