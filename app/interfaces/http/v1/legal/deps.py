"""Dependencies of the legal routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.interfaces.http.v1.id_registration.locale import request_locale
from app.interfaces.http.v1.legal.schemas import AppScopeValue
from app.shared.actor import Actor, Role
from app.shared.contracts.legal import APP_HEADER, normalize_app

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


def get_app(request: Request) -> str:
    """The calling app from ``X-IHSP-App``; unknown or missing means ``global``."""
    return normalize_app(request.headers.get(APP_HEADER))


App = Annotated[str, Depends(get_app)]

AppScopeQuery = Annotated[
    AppScopeValue,
    Query(description="Document scope: global or the name of an app"),
]
