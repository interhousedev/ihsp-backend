"""ID-16, PWA-1: which clients are first party, who may use them, how long they last."""

from app.modules.identity.domain.client_policy import (
    DEFAULT_REFRESH_DAYS,
    FIRST_PARTY_CLIENTS,
    LONG_SESSION_CLIENTS,
    LONG_SESSION_REFRESH_DAYS,
    WEB_CLIENTS,
    is_first_party,
    may_use_client,
    refresh_days,
)
from app.shared.actor import Role

import pytest


def test_the_installed_app_is_a_first_party_web_client() -> None:
    """PWA-1: `app` skips consent and uses the token handler like `sp`."""
    assert "app" in FIRST_PARTY_CLIENTS
    assert "app" in WEB_CLIENTS
    assert is_first_party("app")


def test_the_library_is_a_first_party_web_client_with_the_default_refresh() -> None:
    """LIB-1: `library` skips consent like `sp` and keeps the 30-day refresh."""
    assert "library" in FIRST_PARTY_CLIENTS
    assert is_first_party("library")
    assert refresh_days("library") == DEFAULT_REFRESH_DAYS


@pytest.mark.parametrize(
    "role", [Role.STUDENT, Role.TEACHER, Role.LIBRARIAN, Role.ADMIN]
)
def test_the_library_accepts_students_teachers_librarians_and_admins(
    role: Role,
) -> None:
    """LIB-1, ID-16: any of the four roles opens the library; a mix works too."""
    assert may_use_client("library", [role])
    assert may_use_client("library", [Role.STUDENT, Role.LIBRARIAN])


def test_a_librarian_only_account_signs_in_to_the_library_but_not_to_staff() -> None:
    """LIB-1: `librarian` alone is no teacher and no administrator."""
    assert may_use_client("library", [Role.LIBRARIAN])
    assert not may_use_client("staff", [Role.LIBRARIAN])
    assert not may_use_client("admin", [Role.LIBRARIAN])


def test_the_library_refuses_an_account_without_any_of_its_roles() -> None:
    """LIB-1: an `lms_admin`-only account has no business in the library."""
    assert not may_use_client("library", [Role.LMS_ADMIN])
    assert not may_use_client("library", [])


def test_the_five_original_platforms_stay_first_party() -> None:
    """ID-16: adding `app` removes nobody."""
    assert {"id", "sp", "staff", "admin", "lms"} <= FIRST_PARTY_CLIENTS


def test_the_miniapp_and_strangers_are_not_first_party() -> None:
    """ID-16: only our own web clients skip consent."""
    assert not is_first_party("miniapp")
    assert not is_first_party("evil")


@pytest.mark.parametrize("roles", [[], [Role.STUDENT], [Role.TEACHER], [Role.ADMIN]])
def test_the_installed_app_needs_no_role(roles: list[Role]) -> None:
    """PWA-1: like `sp`, every signed-in person may use `app`."""
    assert may_use_client("app", roles)
    assert may_use_client("sp", roles)


def test_staff_and_admin_still_demand_their_role() -> None:
    """ID-16: the new client changes nothing for the role-gated ones."""
    assert not may_use_client("staff", [Role.STUDENT])
    assert may_use_client("staff", [Role.TEACHER])
    assert not may_use_client("admin", [Role.TEACHER])
    assert may_use_client("admin", [Role.ADMIN])


def test_the_installed_app_keeps_people_signed_in_for_90_days() -> None:
    """PWA-2: the home-screen app refreshes for 90 days."""
    assert refresh_days("app") == 90
    assert LONG_SESSION_REFRESH_DAYS == 90
    assert LONG_SESSION_CLIENTS == frozenset({"app"})


@pytest.mark.parametrize("client_id", ["id", "sp", "staff", "admin", "lms", "library"])
def test_the_websites_keep_the_30_day_refresh(client_id: str) -> None:
    """PWA-2: browsers on the websites stay at 30 days."""
    assert refresh_days(client_id) == 30
    assert DEFAULT_REFRESH_DAYS == 30


def test_an_unknown_client_gets_the_default_refresh() -> None:
    """PWA-2: only listed clients are long-session."""
    assert refresh_days("evil") == DEFAULT_REFRESH_DAYS
