"""POST /v1/id/consent: approve or deny an MCP client."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import ConsentBody, RedirectToResponse


async def post_consent(
    body: ConsentBody, auth: AuthDep, ctx: CtxDep
) -> RedirectToResponse:
    """Create the connector and let Hydra continue."""
    redirect = await auth.accept_consent.execute(
        body.consent_challenge,
        accept=body.accept,
        grant_scopes=body.grant_scopes,
        otp_code=body.otp_code,
        ctx=ctx,
    )
    return RedirectToResponse(redirect_to=redirect)
