"""Dependencies of the admission routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import NotEntitledError
from app.shared.actor import Actor

from fastapi import Depends

ContainerDep = Annotated[Container, Depends(get_container)]
UserActor = Annotated[Actor, Depends(get_actor)]


async def resolve_admission_context(
    container: ContainerDep, actor: UserActor
) -> AdmissionContext:
    """Resolve the caller's admission role without checking entry (for `/me`)."""
    return await container.admission.actor.execute(actor)


async def require_admission_actor(
    ctx: Annotated[AdmissionContext, Depends(resolve_admission_context)],
) -> AdmissionContext:
    """Admit applicants and staff."""
    if not ctx.admission.may_enter:
        raise NotEntitledError()
    return ctx


AnyContext = Annotated[AdmissionContext, Depends(resolve_admission_context)]
AdmissionCtx = Annotated[AdmissionContext, Depends(require_admission_actor)]
