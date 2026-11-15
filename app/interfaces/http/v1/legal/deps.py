"""Dependencies of the legal routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.interfaces.http.v1.id_registration.locale import request_locale
from app.shared.actor import Actor, Role

from fastapi import Depends, Query, Request

ContainerDep = Annotated[Container, Depends(get_container)]
UserActor = Annotated[Actor, Depends(get_actor)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


def get_locale(
    request: Request,
    locale: Annotated[
        str | None,
        Query(
            pattern="^(uz|ru|en)$", description="uz, ru or en; default Accept-Language"
        ),
    ] = None,
) -> str:
    """The language of the texts: ``?locale=``, else ``Accept-Language``."""
    return locale or request_locale(request)


Locale = Annotated[str, Depends(get_locale)]
