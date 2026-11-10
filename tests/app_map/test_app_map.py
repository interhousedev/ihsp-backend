"""The app map: ranking per locale, role filter and the HTTP route."""

from collections.abc import Callable

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.app_map import ROUTERS
from app.settings import Settings, UrlsSettings
from app.shared.actor import Actor, Role
from app.shared.app_map import APP_MAP, for_roles, search
from tests.conftest import HttpClientFactory

import pytest

URLS = UrlsSettings()
STUDENT = frozenset({Role.STUDENT})
TEACHER = frozenset({Role.TEACHER})
ADMIN = frozenset({Role.ADMIN})


def ids(query: str, locale: str, roles: frozenset[Role]) -> list[str]:
    """Destination ids found for the query."""
    return [f.destination.id for f in search(query, locale, roles, URLS)]


@pytest.mark.parametrize(
    ("query", "locale", "expected"),
    [
        ("grades", "en", "sp-grades"),
        ("оценки", "ru", "sp-grades"),
        ("baholar", "uz", "sp-grades"),
        ("справка о болезни", "ru", "sp-excuses"),
        ("face sign-in", "en", "sp-face"),
        ("flash cards", "en", "sp-flashcards"),
    ],
)
def test_search_ranks_the_best_page_first_in_every_locale(
    query: str, locale: str, expected: str
) -> None:
    """The best match is the first answer, whatever language the user writes in."""
    assert ids(query, locale, STUDENT)[0] == expected


def test_search_hides_pages_of_other_roles() -> None:
    """A student never gets admin pages; an admin gets them."""
    assert not any(i.startswith("admin-") for i in ids("vault secrets", "en", STUDENT))
    assert ids("vault", "en", ADMIN)[0] == "admin-vault"


def test_the_same_word_leads_to_the_page_of_the_role() -> None:
    """Excuses are in the student, staff and admin apps; each role gets its own."""
    assert ids("excuses", "en", TEACHER)[0] == "staff-excuses"
    assert ids("excuses", "en", STUDENT)[0] == "sp-excuses"
    assert ids("excuses", "en", ADMIN)[0] == "admin-excuses"


def test_search_returns_absolute_urls_and_nothing_for_nonsense() -> None:
    """Pages resolve against the configured origins; a bot command has no URL."""
    found = search("homework", "en", STUDENT, URLS)
    assert found[0].url == f"{URLS.sp}/homework/"
    assert any(f.url is None for f in search("marks telegram", "en", STUDENT, URLS))
    assert search("zzzzqqq", "en", STUDENT, URLS) == []


def test_every_destination_has_all_locales_and_unique_ids() -> None:
    """The map is complete: uz, ru and en titles, unique ids, rooted paths."""
    assert len({d.id for d in APP_MAP}) == len(APP_MAP)
    for d in APP_MAP:
        assert set(d.title) == {"uz", "ru", "en"}
        assert d.path.startswith("/")
        assert d.keywords


async def test_the_route_lists_only_pages_of_the_callers_roles(
    http_client: HttpClientFactory,
    settings: Settings,
    make_actor: Callable[..., Actor],
) -> None:
    """GET /v1/app-map is filtered by the roles of the token."""
    student = make_actor(Role.STUDENT)
    client = await http_client(ROUTERS, {get_actor: lambda: student})

    response = await client.get("/v1/app-map")

    assert response.status_code == 200
    body = response.json()["items"]
    assert {i["id"] for i in body} == {
        f.destination.id for f in for_roles(settings.urls, student.roles)
    }
    assert not any(i["app"] == "admin" for i in body)
    assert set(body[0]) == {"id", "app", "path", "url", "title", "keywords"}


async def test_the_route_needs_a_token(http_client: HttpClientFactory) -> None:
    """No Authorization header: 401."""
    client = await http_client(ROUTERS)

    assert (await client.get("/v1/app-map")).status_code == 401
