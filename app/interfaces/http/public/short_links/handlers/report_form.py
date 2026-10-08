"""GET and POST .../{slug}/report: the no-JavaScript report form (SL-9)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.public.short_links.web_response import to_response

from fastapi import Depends, Form, Request, Response


async def show_report_form(
    slug: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> Response:
    """Show the report form of a short link."""
    result = await container.links.report_pages.show(
        slug, ip=ip, accept_language=request.headers.get("accept-language")
    )
    return to_response(result)


async def submit_report_form(
    slug: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
    reason: Annotated[str, Form(max_length=40)] = "other",
    comment: Annotated[str | None, Form(max_length=500)] = None,
) -> Response:
    """Record the report and show the thank-you page."""
    result = await container.links.report_pages.submit(
        slug,
        reason=reason,
        comment=comment,
        ip=ip,
        accept_language=request.headers.get("accept-language"),
    )
    return to_response(result)
