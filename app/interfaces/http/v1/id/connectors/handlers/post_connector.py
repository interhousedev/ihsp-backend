"""POST /v1/id/me/connectors: issue a token connector."""

from app.interfaces.http.v1.id.connectors.schemas import (
    ConnectorResponse,
    CreateConnectorBody,
    NewConnectorResponse,
)
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep


async def post_connector(
    body: CreateConnectorBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> NewConnectorResponse:
    """Create the connector; the token is in this response only."""
    created = await auth.create_connector.execute(
        actor,
        server=body.server,
        name=body.name,
        scopes=body.scopes,
        course_ids=body.course_ids,
        expires_in_days=body.expires_in_days,
        otp_code=body.otp_code,
        ctx=ctx,
    )
    return NewConnectorResponse(
        connector=ConnectorResponse.of(created.connector), token=created.token
    )
