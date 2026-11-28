"""The Students MCP server: the student's own data and own flash cards (MCP-1)."""

from app.interfaces.mcp import upload_file
from app.interfaces.mcp.catalog import CatalogMcp
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import finish_catalog, make_toolkit
from app.interfaces.mcp.student.tools import (
    add_flashcards,
    clubs_read,
    clubs_write,
    create_flashcard_set,
    find_feature,
    get_attendance,
    get_flashcard_set,
    get_homework,
    get_lesson_materials,
    get_marks,
    get_my_subjects,
    get_results,
    get_schedule,
    get_subject_lessons,
    learning_record,
    list_files,
    list_flashcard_sets,
    my_ai_reviews,
    my_attempts,
    read_file,
    search_files,
    update_flashcard,
)
from app.interfaces.mcp.student.tools.groups import academic, content, files_courses
from app.shared.brand import current_brand

from mcp.server.fastmcp import FastMCP

TOOL_MODULES = (
    get_schedule,
    find_feature,
    get_my_subjects,
    get_subject_lessons,
    get_homework,
    get_marks,
    get_results,
    get_attendance,
    get_lesson_materials,
    list_files,
    read_file,
    search_files,
    list_flashcard_sets,
    get_flashcard_set,
    create_flashcard_set,
    add_flashcards,
    update_flashcard,
    learning_record,
    my_attempts,
    my_ai_reviews,
    *academic.TOOL_MODULES,
    *content.TOOL_MODULES,
    *files_courses.TOOL_MODULES,
    upload_file,
    clubs_read,
    clubs_write,
)


def build_student_server(deps: McpDeps) -> FastMCP:
    """Create the Students server with all its tools registered."""
    kit = make_toolkit(
        deps,
        "student",
        title=f"{current_brand().name} Students",
        instructions_key="mcp-instructions-student",
        cls=CatalogMcp,
    )
    for module in TOOL_MODULES:
        module.register(kit)
    finish_catalog(
        kit, "student", ["find_feature", "get_schedule", "get_homework", "get_marks"]
    )
    return kit.mcp
