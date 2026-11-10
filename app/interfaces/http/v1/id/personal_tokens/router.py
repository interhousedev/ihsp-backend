"""Routes /v1/id/personal-tokens*: personal API tokens (ihsp_pat_)."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep
from app.interfaces.http.v1.id.personal_tokens.schemas import (
    CreatePersonalTokenBody,
    NewPersonalTokenResponse,
    PersonalTokenResponse,
)

from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/v1/id/personal-tokens", tags=["id-personal-tokens"])


@router.get("", response_model=list[PersonalTokenResponse])
async def list_personal_tokens(
    actor: ActorDep, auth: AuthDep
) -> list[PersonalTokenResponse]:
    """The caller's tokens, newest first."""
    tokens = await auth.list_personal_tokens.execute(actor)
    return [PersonalTokenResponse.of(token) for token in tokens]


@router.post(
    "", response_model=NewPersonalTokenResponse, status_code=status.HTTP_201_CREATED
)
async def create_personal_token(
    body: CreatePersonalTokenBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> NewPersonalTokenResponse:
    """Create a token (OTP step-up); the secret is in this response only."""
    created = await auth.create_personal_token.execute(
        actor,
        name=body.name,
        scopes=list(body.scopes),
        expires_in_days=body.expires_in_days,
        otp_code=body.otp_code,
        ctx=ctx,
    )
    return NewPersonalTokenResponse(
        personal_token=PersonalTokenResponse.of(created.token), token=created.secret
    )


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_personal_token(
    token_id: UUID, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Revoke at once."""
    await auth.revoke_personal_token.execute(actor, token_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
