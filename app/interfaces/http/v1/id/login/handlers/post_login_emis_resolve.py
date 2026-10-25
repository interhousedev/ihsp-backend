"""POST /v1/id/login/emis/resolve: is this EMIS ID registered? Never says whose."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import (
    EmisLoginBody,
    EmisLoginCheckResponse,
)


async def post_login_emis_resolve(
    body: EmisLoginBody, auth: AuthDep, ctx: CtxDep
) -> EmisLoginCheckResponse:
    """Answer registered=true; an unregistered ID gets a problem+json 404."""
    await auth.resolve_emis_login.execute(body.emis_id, ctx=ctx)
    return EmisLoginCheckResponse()
