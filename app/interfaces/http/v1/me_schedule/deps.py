"""Dependencies of the profile and timetable routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends

ContainerDep = Annotated[Container, Depends(get_container)]
StudentActor = Annotated[Actor, Depends(require_roles(Role.STUDENT))]
TeacherActor = Annotated[Actor, Depends(require_roles(Role.TEACHER))]
