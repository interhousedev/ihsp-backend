"""The assistant's find_feature tool: ranked by locale, filtered by role."""

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.find_feature import FindFeature
from app.settings import UrlsSettings
from app.shared.actor import Actor, Role
from app.shared.ids import new_id

import pytest

URLS = UrlsSettings()


def ctx(role: Role, locale: str) -> ToolContext:
    """A tool context of an actor with one role."""
    actor = Actor(user_id=new_id(), roles=frozenset({role}))
    return ToolContext(actor=actor, chat_id=new_id(), locale=locale)


async def run(query: str, role: Role, locale: str) -> dict[str, object]:
    """Run the tool."""
    tool = FindFeature(URLS)
    return await tool.run(tool.parse({"query": query}), ctx(role, locale))


@pytest.mark.parametrize(
    ("query", "locale", "title"),
    [
        ("оценки", "ru", "Оценки"),
        ("baholar", "uz", "Baholar"),
        ("grades", "en", "Grades"),
    ],
)
async def test_the_title_comes_in_the_users_language(
    query: str, locale: str, title: str
) -> None:
    """The best hit is the grades page, titled in the chat's locale, with a link."""
    result = await run(query, Role.STUDENT, locale)

    first = result["items"][0]  # type: ignore[index]
    assert first["title"] == title
    assert first["url"] == f"{URLS.sp}/grades/"


async def test_a_student_is_never_pointed_to_an_admin_page() -> None:
    """The role filter holds: the same query leads an admin to the admin page."""
    student = await run("vault", Role.STUDENT, "en")
    admin = await run("vault", Role.ADMIN, "en")

    assert student["found"] is False
    assert admin["items"][0]["url"] == f"{URLS.admin}/vault/"  # type: ignore[index]
