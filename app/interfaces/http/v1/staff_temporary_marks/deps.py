"""Dependencies of the staff temporary gradebook routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends

ContainerDep = Annotated[Container, Depends(get_container)]
TeacherActor = Annotated[Actor, Depends(require_roles(Role.TEACHER))]
StaffActor = Annotated[Actor, Depends(require_roles(Role.TEACHER, Role.ADMIN))]
