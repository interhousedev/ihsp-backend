"""Per-app skills: each web app offers its own tools and names itself to the model."""

from typing import Any

from app.modules.ai.application.tools.app_skills import (
    app_for,
    app_section,
    skill_for,
)
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.tool_args import ToolArgs

STUDENT_POOL = [
    "get_schedule",
    "get_marks",
    "get_homework",
    "get_attendance",
    "get_my_subjects",
    "get_subject_lessons",
    "get_lesson_materials",
    "list_files",
    "read_file",
    "search_files",
    "search_knowledge_base",
    "search_web",
    "find_feature",
    "list_notebooks",
    "get_notebook",
    "search_notebook",
    "list_notebook_artifacts",
    "create_artifact",
    "library_search",
]
ADMIN_POOL = ["list_groups", "find_feature", "search_knowledge_base"]
ADMISSION_POOL = [
    "admission_get_application",
    "admission_search_faq",
    "admission_suggest",
    "admission_find_courses",
    "admission_add_suggestion",
]
STAFF_TOOLS = {
    "get_schedule",
    "get_my_subjects",
    "get_subject_lessons",
    "get_lesson_materials",
    "list_files",
    "read_file",
    "search_files",
    "search_knowledge_base",
    "search_web",
    "find_feature",
    "list_notebooks",
    "get_notebook",
    "search_notebook",
    "list_notebook_artifacts",
    "create_artifact",
}
# The teachers' pool: the staff tools plus the tools that only teachers have.
STAFF_POOL = [*sorted(STAFF_TOOLS), "list_my_groups"]
DEFAULT_STUDENT = set(STUDENT_POOL) - {"library_search"}


class NoArgs(ToolArgs):
    """No arguments."""


class FakeTool(ReadTool[NoArgs]):
    """A read tool that only has a name; the registry never runs it here."""

    args_model = NoArgs

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name

    async def run(self, args: NoArgs, ctx: ToolContext) -> dict[str, Any]:
        return {}


def registry() -> ToolRegistry:
    """A registry whose pools hold the production tool names."""
    return ToolRegistry(
        student=[FakeTool(n) for n in STUDENT_POOL],
        admin=[FakeTool(n) for n in ADMIN_POOL],
        admission=[FakeTool(n) for n in ADMISSION_POOL],
        staff=[FakeTool(n) for n in STAFF_POOL],
    )


def names(
    assistant: Assistant, app: str | None = None, surface: str = "web"
) -> set[str]:
    """The names of the tools a model request of this chat is offered."""
    tools = registry().llm_tools(assistant, app=app, surface=surface)
    return {t["function"]["name"] for t in tools}


def test_admission_app_gets_only_admission_tools() -> None:
    """The admission app's chats offer the admission_* tools and nothing else."""
    offered = names(Assistant.ADMISSION, "admission")

    assert offered == set(ADMISSION_POOL)
    assert all(name.startswith("admission_") for name in offered)


def test_library_app_gets_library_tools() -> None:
    """The library app offers library_search and find_feature, not student data."""
    offered = names(Assistant.STUDENT, "library")

    assert offered == {"library_search", "find_feature"}


def test_library_search_is_hidden_outside_its_app() -> None:
    """The default student set does not offer the library tool."""
    assert "library_search" not in names(Assistant.STUDENT)
    assert "library_search" not in names(Assistant.STUDENT, "sp")


def test_staff_app_gets_the_staff_pool() -> None:
    """Teachers get the staff pool: no marks, homework or attendance."""
    offered = names(Assistant.STUDENT, "staff")

    assert offered == set(STAFF_POOL)
    assert not offered & {"get_marks", "get_homework", "get_attendance"}


def test_staff_app_does_not_draw_from_the_student_pool() -> None:
    """A teacher's tool that the student pool lacks is offered; no student tool is."""
    offered = names(Assistant.STUDENT, "staff")

    assert "list_my_groups" in offered
    assert offered <= set(STAFF_POOL)
    assert "list_my_groups" not in names(Assistant.STUDENT, "sp")


def test_student_app_keeps_the_default_student_set() -> None:
    """The student app offers what the student assistant always offered."""
    assert names(Assistant.STUDENT, "sp") == DEFAULT_STUDENT


def test_admin_app_gets_the_admin_pool() -> None:
    """The administration app offers its own pool."""
    assert names(Assistant.ADMIN, "admin") == set(ADMIN_POOL)


def test_unknown_app_gets_the_default_set() -> None:
    """An unknown or missing app falls back to the chat's default tools."""
    default = names(Assistant.STUDENT)

    assert names(Assistant.STUDENT, "no-such-app") == default
    assert names(Assistant.STUDENT, "") == default
    assert default == DEFAULT_STUDENT


def test_a_skill_never_selects_tools_of_another_assistant() -> None:
    """The staff skill draws from its own pool; an admin chat keeps its pool."""
    assert names(Assistant.ADMIN, "staff") == set(ADMIN_POOL)


def test_skill_for_knows_the_web_apps_only() -> None:
    """Skills exist for the six web apps; bot, id and unknown names have none."""
    for app in ("sp", "staff", "admin", "lms", "library", "admission"):
        assert skill_for(app) is not None
    for app in ("bot", "id", "share", "nope", None):
        assert skill_for(app) is None


def test_app_section_names_the_app_with_brand_placeholders() -> None:
    """The prompt section is filled from the brand and never shows a placeholder."""
    section = app_section("library")

    assert section
    assert "{brand}" not in section
    assert "library" in section.lower()
    assert app_section("nope") == ""


def test_telegram_tools_are_still_offered_in_every_app() -> None:
    """The bot's tools do not depend on the app (they are added on its surface)."""
    tools = ToolRegistry(
        student=[FakeTool("library_search")],
        admin=[],
        telegram=[FakeTool("bot_only")],
    ).llm_tools(Assistant.STUDENT, app="library", surface="telegram")

    assert {t["function"]["name"] for t in tools} == {"library_search", "bot_only"}


def test_header_names_the_app() -> None:
    """The X-IHSP-App header is the app of the request."""
    assert app_for("staff", "sp") == "staff"
    assert app_for(" Library ", None) == "library"


def test_client_id_names_the_app_when_the_header_is_absent() -> None:
    """Without the header the OAuth client of the token names the app."""
    assert app_for(None, "staff") == "staff"
    assert app_for(None, "admin") == "admin"
    assert app_for(None, "lms") == "lms"
    assert app_for(None, "library") == "library"
    assert app_for(None, "admission") == "admission"
    assert app_for(None, "sp") == "sp"
    assert app_for("", "staff") == "staff"


def test_app_and_miniapp_clients_are_the_student_app() -> None:
    """The installable PWA and the Telegram mini app both use the student skill."""
    assert app_for(None, "app") == "sp"
    assert app_for(None, "miniapp") == "sp"


def test_unknown_client_id_has_no_app() -> None:
    """A client that is not a web app (or no client at all) gets no app."""
    assert app_for(None, "some-third-party") is None
    assert app_for(None, None) is None
    assert app_for(None, "") is None
