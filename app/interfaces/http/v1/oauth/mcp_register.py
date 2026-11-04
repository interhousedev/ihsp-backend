"""POST /v1/oauth/mcp/register: RFC 7591 registration of MCP clients."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.modules.identity.application.mcp_clients import RegistrationRefusedError

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/oauth/mcp", tags=["oauth"])

Uri = Annotated[str, Field(min_length=1, max_length=512)]


class RegisterBody(BaseModel):
    """The fields that are read; any other client metadata is ignored."""

    redirect_uris: list[Uri] = Field(min_length=1, max_length=5)
    client_name: str | None = Field(default=None, max_length=200)
    token_endpoint_auth_method: str | None = Field(default=None, max_length=40)


class RegisterResponse(BaseModel):
    """RFC 7591 section 3.2.1. `client_secret` only for a confidential client."""

    client_id: str
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    scope: str
    client_secret: str | None = None
    client_secret_expires_at: int | None = None


class RegisterError(BaseModel):
    """RFC 7591 section 3.2.2."""

    error: str
    error_description: str


@router.post(
    "/register",
    status_code=201,
    response_model=RegisterResponse,
    response_model_exclude_none=True,
    responses={400: {"model": RegisterError}},
    operation_id="register_mcp_client",
)
async def register_mcp_client(
    body: RegisterBody, auth: AuthDep, ctx: CtxDep
) -> RegisterResponse | JSONResponse:
    """Register a client whose redirect URIs are on the allowlist."""
    try:
        created = await auth.register_mcp_client.execute(
            redirect_uris=body.redirect_uris,
            client_name=body.client_name,
            auth_method=body.token_endpoint_auth_method,
            ctx=ctx,
        )
    except RegistrationRefusedError as refused:
        return JSONResponse(
            status_code=400,
            content={
                "error": refused.error,
                "error_description": refused.description,
            },
            headers={"Cache-Control": "no-store"},
        )
    client = created.client
    return RegisterResponse(
        client_id=client.client_id,
        client_name=client.client_name,
        redirect_uris=list(client.redirect_uris),
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=created.auth_method,
        scope=auth.register_mcp_client.scope,
        client_secret=created.client_secret,
        client_secret_expires_at=0 if created.client_secret else None,
    )
