"""Dependencies of the certificates routes."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.modules.certificates.application.staff_scope import StaffFilters
from app.modules.certificates.domain.custom_fields import KEY_RE
from app.modules.certificates.domain.errors import CertificateInvalidError
from app.shared.actor import Actor, Role

from fastapi import Depends, Request

ContainerDep = Annotated[Container, Depends(get_container)]
AnyActor = Annotated[Actor, Depends(get_actor)]
StudentActor = Annotated[Actor, Depends(require_roles(Role.STUDENT))]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]
StaffActor = Annotated[Actor, Depends(require_roles(Role.ADMIN, Role.TEACHER))]


CUSTOM_PREFIX = "cf_"
RANGE_MIN_PREFIX = "cfmin_"
RANGE_MAX_PREFIX = "cfmax_"


def custom_query(
    pairs: list[tuple[str, str]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[float | None, float | None]]]:
    """Split the custom field query parameters into value lists and number ranges.

    ``cf_<key>=v`` selects values, ``cfmin_<key>`` and ``cfmax_<key>`` bound numbers.
    """
    values: dict[str, list[str]] = {}
    bounds: dict[str, list[float | None]] = {}
    for name, raw in pairs:
        if name.startswith(CUSTOM_PREFIX):
            key = name[len(CUSTOM_PREFIX) :]
            if KEY_RE.match(key):
                values.setdefault(key, []).append(raw)
        elif name.startswith((RANGE_MIN_PREFIX, RANGE_MAX_PREFIX)):
            is_min = name.startswith(RANGE_MIN_PREFIX)
            key = name[len(RANGE_MIN_PREFIX if is_min else RANGE_MAX_PREFIX) :]
            if KEY_RE.match(key):
                low, high = bounds.setdefault(key, [None, None])
                number = _number(key, raw)
                bounds[key] = [number, high] if is_min else [low, number]
    ranges = {k: (lo, hi) for k, (lo, hi) in bounds.items()}
    return {k: tuple(v) for k, v in values.items()}, ranges


def _number(key: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise CertificateInvalidError(params={"field": key}) from None


def staff_filters(
    request: Request,
    group_id: UUID | None = None,
    subgroup: str | None = None,
    type_id: UUID | None = None,
    subject: str | None = None,
    level: str | None = None,
    student_id: UUID | None = None,
    q: str | None = None,
) -> StaffFilters:
    """Read the staff filters from the query string, custom field filters included."""
    custom, ranges = custom_query(list(request.query_params.multi_items()))
    return StaffFilters(
        group_id=group_id,
        subgroup=subgroup,
        type_id=type_id,
        subject=subject,
        level=level,
        student_id=student_id,
        q=q,
        custom=custom,
        ranges=ranges,
    )


FiltersDep = Annotated[StaffFilters, Depends(staff_filters)]
