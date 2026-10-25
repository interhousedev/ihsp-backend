"""Routes /v1/admin/login-cues*: pre-registration of EMIS logins (admin only)."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.admin_users.login_cues.schemas import (
    BulkLoginCuesBody,
    BulkLoginCuesResponse,
    LoginCueBody,
    LoginCueResponse,
)
from app.interfaces.http.v1.id.dependencies import AdminDep

from fastapi import APIRouter, Depends, Response, status

router = APIRouter(prefix="/v1/admin/login-cues", tags=["admin-login-cues"])


@router.get("", response_model=list[LoginCueResponse])
async def list_login_cues(
    _admin: AdminDep,
    container: Annotated[Container, Depends(get_container)],
    group_id: UUID | None = None,
) -> list[LoginCueResponse]:
    """Cues, newest first; logins are masked (last two characters only)."""
    views = await container.identity.emis.login_cues.list_for_admin(group_id)
    return [LoginCueResponse.from_view(view) for view in views]


@router.post("", response_model=LoginCueResponse, status_code=status.HTTP_201_CREATED)
async def create_login_cue(
    body: LoginCueBody,
    _admin: AdminDep,
    container: Annotated[Container, Depends(get_container)],
) -> LoginCueResponse:
    """Pre-register one student."""
    (view,) = await container.identity.emis.login_cues.create([body.to_command()])
    return LoginCueResponse.from_view(view)


@router.post(
    "/bulk", response_model=BulkLoginCuesResponse, status_code=status.HTTP_201_CREATED
)
async def bulk_create_login_cues(
    body: BulkLoginCuesBody,
    _admin: AdminDep,
    container: Annotated[Container, Depends(get_container)],
) -> BulkLoginCuesResponse:
    """Pre-register several students; all or nothing."""
    views = await container.identity.emis.login_cues.create(
        [item.to_command() for item in body.items]
    )
    return BulkLoginCuesResponse(
        created=[LoginCueResponse.from_view(view) for view in views]
    )


@router.delete("/{cue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_login_cue(
    cue_id: UUID,
    _admin: AdminDep,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Delete a cue (consumed ones too)."""
    await container.identity.emis.login_cues.delete(cue_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
