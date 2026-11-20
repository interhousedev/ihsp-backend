"""Per-app skills: the tools the assistant offers in each web app.

It also says what the assistant knows of the app.

The app of a request is its `X-IHSP-App` header; without it, the OAuth client of the
token names the app. An unknown or missing app has no skill and gets the chat's
default tools and prompt.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.ai.domain.assistant import Assistant
from app.shared.brand import with_brand
from app.shared.contracts.legal import normalize_app


@dataclass(frozen=True, slots=True)
class AppSkill:
    """One app's skill.

    `staff_pool` offers the teachers' pool (the registry's staff tools) instead of the
    assistant's own pool. `tools` names the tools offered from that pool; None offers
    the whole pool (minus the tools that are never offered by default).
    """

    assistant: Assistant
    tools: frozenset[str] | None
    section: str
    staff_pool: bool = False


SKILLS: Final[dict[str, AppSkill]] = {
    "sp": AppSkill(
        Assistant.STUDENT,
        None,
        "The user is in the student app of {brand}: timetable, marks, homework, "
        "attendance, subjects, lesson materials, files and notebooks.",
    ),
    "staff": AppSkill(
        Assistant.STUDENT,
        None,
        "The user is a teacher in the staff app of {brand}: timetable, subjects and "
        "lesson materials, files, notebooks and documents.",
        staff_pool=True,
    ),
    "admin": AppSkill(
        Assistant.ADMIN,
        None,
        "The user is in the administration app of {brand}: people, groups, timetable "
        "and school administration through the admin tools.",
    ),
    "lms": AppSkill(
        Assistant.LMS_AUTHOR,
        None,
        "The user is in the course authoring app of {brand}: they build the outline, "
        "sections, steps and blocks of courses.",
    ),
    "library": AppSkill(
        Assistant.STUDENT,
        frozenset({"library_search", "find_feature"}),
        "The user is in the library app of {brand}: search the library's books and "
        "articles and read their text.",
    ),
    "admission": AppSkill(
        Assistant.ADMISSION,
        None,
        "The user is in the admission app of {brand}: their application, deadlines, "
        "university suggestions, courses and questions about admission.",
    ),
}

# The OAuth client of a token names the web app that holds it (used without the header).
CLIENT_APPS: Final[dict[str, str]] = {
    "sp": "sp",
    "app": "sp",
    "miniapp": "sp",
    "staff": "staff",
    "admin": "admin",
    "lms": "lms",
    "library": "library",
    "admission": "admission",
}


def app_for(header: str | None, client_id: str | None) -> str | None:
    """The app of a request: the `X-IHSP-App` header, else the token's OAuth client.

    The header wins when it is sent (an unknown name is `global`, which has no skill).
    None means the request names no web app.
    """
    if header and header.strip():
        return normalize_app(header)
    return CLIENT_APPS.get(client_id or "")


def skill_for(app: str | None) -> AppSkill | None:
    """The skill of a web app, or None for an unknown or missing app."""
    return SKILLS.get(app) if app else None


def app_section(app: str | None) -> str:
    """The system prompt section of an app with brand placeholders filled, or ""."""
    skill = skill_for(app)
    return with_brand(skill.section) if skill else ""
