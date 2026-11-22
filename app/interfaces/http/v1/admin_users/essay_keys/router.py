"""Backup, restore and rotation of the essay data keys (/v1/admin/essay-keys)."""

import json
from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.admin_users.essay_keys.schemas import (
    EssayKeysStatusResponse,
    PassphraseBody,
    RestoreBody,
    RestoreResponse,
)
from app.interfaces.http.v1.id.dependencies import AdminDep

from fastapi import APIRouter, Depends, Response, status

router = APIRouter(prefix="/v1/admin/essay-keys", tags=["admin-essay-keys"])

ContainerDep = Annotated[Container, Depends(get_container)]


@router.get("/status", response_model=EssayKeysStatusResponse)
async def get_status(
    admin: AdminDep, container: ContainerDep
) -> EssayKeysStatusResponse:
    """Students with a key, key generation, its backup and the rotation progress."""
    result = await container.admission.essay_keys.status(admin)
    return EssayKeysStatusResponse.from_status(result)


@router.post(
    "/backup",
    response_class=Response,
    responses={
        200: {"content": {"application/json": {}}, "description": "Backup file"}
    },
)
async def post_backup(
    body: PassphraseBody, admin: AdminDep, container: ContainerDep
) -> Response:
    """The one passphrase-sealed backup of the current generation (409 after it)."""
    file = await container.admission.essay_keys.backup(admin, body.passphrase)
    return Response(
        content=file.content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{file.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/restore", response_model=RestoreResponse)
async def post_restore(
    body: RestoreBody, admin: AdminDep, container: ContainerDep
) -> RestoreResponse:
    """Write the keys missing from Vault; an existing key is never overwritten."""
    data = json.dumps(body.backup).encode()
    report = await container.admission.essay_keys.restore(admin, data, body.passphrase)
    return RestoreResponse.from_report(report)


@router.post(
    "/rotate",
    response_model=EssayKeysStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_rotate(
    admin: AdminDep, container: ContainerDep
) -> EssayKeysStatusResponse:
    """Start the rotation in the worker; poll /status for progress."""
    ledger = await container.admission.essay_keys.rotate(admin)
    return EssayKeysStatusResponse.build(ledger, None)
