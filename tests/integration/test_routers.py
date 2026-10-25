"""Router registration: every package mounts, no route is served twice."""

from collections import Counter

from app.interfaces.http.routing import (
    API_PACKAGES,
    IDENTITY_PACKAGES,
    collect_routers,
    routers_for,
)

import pytest


def _operations(process: str) -> Counter[tuple[str, str]]:
    found: Counter[tuple[str, str]] = Counter()
    for router in routers_for(process):
        for route in router.routes:
            path = getattr(route, "path", "")
            for method in getattr(route, "methods", None) or ():
                found[(method, path)] += 1
    return found


@pytest.mark.parametrize("package", IDENTITY_PACKAGES + API_PACKAGES)
def test_every_router_package_exposes_routers(package: str) -> None:
    """A missing or empty package would silently drop its endpoints."""
    assert collect_routers((package,)), package


@pytest.mark.parametrize("process", ["all", "identity", "api"])
def test_no_route_is_mounted_twice(process: str) -> None:
    """The same method and path never appears twice in one process."""
    duplicates = [key for key, count in _operations(process).items() if count > 1]

    assert duplicates == []


def test_identity_and_api_do_not_overlap() -> None:
    """Splitting `all` into `identity` and `api` loses and repeats nothing."""
    identity = set(_operations("identity"))
    api = set(_operations("api"))
    everything = set(_operations("all"))

    assert identity & api == set()
    assert identity | api == everything


def test_composition_routes_come_before_admin_groups() -> None:
    """`/v1/admin/groups/stats` must not be taken for `/v1/admin/groups/{id}`."""
    paths = [
        getattr(route, "path", "")
        for router in routers_for("api")
        for route in router.routes
    ]

    assert paths.index("/v1/admin/groups/stats") < paths.index(
        "/v1/admin/groups/{group_id}"
    )
