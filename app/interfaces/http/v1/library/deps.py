"""Dependencies of the library routes: the module, the caller, the language."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import (
    get_actor,
    get_container,
    get_optional_actor,
    require_roles,
)
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor, Role

from fastapi import Depends, Header

_librarian = require_roles(Role.LIBRARIAN, Role.ADMIN)
_admin = require_roles(Role.ADMIN)
_teacher = require_roles(Role.TEACHER, Role.LIBRARIAN, Role.ADMIN)


async def get_library(
    container: Annotated[Container, Depends(get_container)],
) -> LibraryServices:
    """The library use cases (the routes vanish with `FEATURES__LIBRARY=false`)."""
    return container.library


Library = Annotated[LibraryServices, Depends(get_library)]
# Any signed-in lyceum user.
SignedIn = Annotated[Actor, Depends(get_actor)]
# Anonymous visitors are allowed: public items only.
MaybeSignedIn = Annotated[Actor | None, Depends(get_optional_actor)]
LibrarianActor = Annotated[Actor, Depends(_librarian)]
AdminActor = Annotated[Actor, Depends(_admin)]
# Teachers, librarians and Administration (reading lists, book plans).
TeachingActor = Annotated[Actor, Depends(_teacher)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language")]
