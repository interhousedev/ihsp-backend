"""Dependencies of the notebook routes: the caller, the module, the switches.

Listing, creating, copying and the usage are for students and teachers; the
subject/lesson routes are for students. The routes of one notebook
(`/v1/notebooks/{id}/...`) take any signed-in user: the use case decides (a
student's own notebook, or the workspace of a course the user is staff of).
"""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.interfaces.http.v1.notebooks.schemas_common import CHAT_MODALITIES
from app.modules.notebooks.domain.errors import FeatureDisabledError
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor, Role
from app.shared.ai_tasks import AiTask
from app.shared.features import Feature, is_enabled

from fastapi import Depends

_student = require_roles(Role.STUDENT)
_owner = require_roles(Role.STUDENT, Role.TEACHER)
_admin = require_roles(Role.ADMIN)


async def get_notebooks(
    container: Annotated[Container, Depends(get_container)],
) -> NotebooksServices:
    """The notebooks use cases; a switched-off feature answers 404 (§ 4.7).

    `FEATURES__NOTEBOOKS=false` removes the routes; `NOTEBOOKS__ENABLED=false`, the
    older switch, keeps them and answers `notebooks/feature-disabled`.
    """
    if not is_enabled(container.settings, Feature.NOTEBOOKS):
        raise FeatureDisabledError(params={"feature": "notebooks"})
    CHAT_MODALITIES.set(container.settings.ai_profile(AiTask.NOTEBOOK_CHAT).modalities)
    return container.notebooks


async def get_workspace_notebooks(
    container: Annotated[Container, Depends(get_container)],
) -> NotebooksServices:
    """The notebooks use cases for course workspaces: notebooks and the LMS on."""
    services = await get_notebooks(container)
    if not is_enabled(container.settings, Feature.LMS):
        raise FeatureDisabledError(params={"feature": "lms"})
    return services


StudentActor = Annotated[Actor, Depends(_student)]
AdminActor = Annotated[Actor, Depends(_admin)]
OwnerActor = Annotated[Actor, Depends(_owner)]  # students and teachers own notebooks
MemberActor = Annotated[Actor, Depends(get_actor)]  # access is checked per notebook
Notebooks = Annotated[NotebooksServices, Depends(get_notebooks)]
WorkspaceNotebooks = Annotated[NotebooksServices, Depends(get_workspace_notebooks)]
