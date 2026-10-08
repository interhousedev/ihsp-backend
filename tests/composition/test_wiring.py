"""Wiring entry points: composition_from_container, install_composition."""

from types import SimpleNamespace
from typing import cast

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.composition import ROUTERS
from app.interfaces.http.v1.composition.wiring import (
    composition_from_container,
    install_composition,
)
from tests.composition.conftest import World, actor_of
from tests.conftest import HttpClientFactory

from fastapi import FastAPI


def module_services(world: World) -> Container:
    """A container-shaped object with the module paths the wiring reads."""
    return cast(
        Container,
        SimpleNamespace(
            settings=world.settings,
            clock=world.clock,
            identity=SimpleNamespace(directory=world.identity),
            academic=SimpleNamespace(
                schedule=SimpleNamespace(queries=world.schedule),
                classwork=SimpleNamespace(queries=world.classwork),
                marks=SimpleNamespace(queries=world.marks),
            ),
            ai=SimpleNamespace(public=world.ai),
            flashcards=SimpleNamespace(public=world.flashcards),
        ),
    )


def test_the_contracts_are_read_from_the_module_services(world: World) -> None:
    """Wiring: container.identity.directory, academic.*.queries, ai.public, ..."""
    composition = composition_from_container(module_services(world), world.ports)

    assert composition.build_alerts.identity is world.identity
    assert composition.build_alerts.schedule is world.schedule
    assert composition.build_alerts.ai is world.ai
    assert composition.search_all.classwork is world.classwork
    assert composition.search_all.marks is world.marks
    assert composition.search_all.flashcards is world.flashcards
    assert composition.build_group_stats.marks is world.marks


def test_the_local_ports_are_shared_between_the_use_cases(world: World) -> None:
    """Wiring: one store serves the token creation and the feed."""
    composition = composition_from_container(module_services(world), world.ports)

    assert composition.issue_calendar_token.tokens is world.tokens
    assert composition.build_calendar_feed.tokens is world.tokens
    assert composition.build_admin_dashboard.sync is world.sync
    assert composition.build_alerts.sync is world.sync


def test_urls_and_calendar_name_come_from_the_settings(world: World) -> None:
    """Wiring: URLS__API, the app name and the app URLs of the alerts."""
    composition = composition_from_container(module_services(world), world.ports)

    assert composition.issue_calendar_token.api_url == world.settings.urls.api.rstrip(
        "/"
    )
    assert composition.build_calendar_feed.calendar_name == (
        world.settings.public_app_name
    )
    assert composition.build_alerts.urls is world.settings.urls


def test_install_composition_puts_it_on_the_app(world: World) -> None:
    """Wiring: handlers find the composition on app.state."""
    app = FastAPI()

    install_composition(app, world.composition)

    assert app.state.composition is world.composition


async def test_an_app_without_the_composition_answers_a_server_error(
    world: World, http_client: HttpClientFactory
) -> None:
    """A forgotten install_composition is a 500, never a silent empty answer."""
    student = world.add_student()
    client = await http_client(
        ROUTERS, overrides={get_actor: lambda: actor_of(student)}
    )

    response = await client.get("/v1/me/alerts")

    assert response.status_code == 500
    assert response.json()["type"] == "common/internal"
