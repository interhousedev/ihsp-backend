"""Routes /v1/admin/vault*: seal status and unseal (administrators only)."""

from app.interfaces.http.v1.admin_users.vault.schemas import (
    VaultStatusResponse,
    VaultUnsealBody,
)
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/vault", tags=["admin-vault"])


@router.get("/status", response_model=VaultStatusResponse)
async def vault_status(admin: AdminDep, auth: AuthDep) -> VaultStatusResponse:
    """Seal state of Vault."""
    return VaultStatusResponse.of(await auth.get_vault_status.execute(admin))


@router.post("/unseal", response_model=VaultStatusResponse)
async def vault_unseal(
    body: VaultUnsealBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> VaultStatusResponse:
    """Submit one unseal key share."""
    state = await auth.unseal_vault.execute(admin, key=body.key, ctx=ctx)
    return VaultStatusResponse.of(state)
