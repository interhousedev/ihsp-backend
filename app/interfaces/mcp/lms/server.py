"""The LMS Course MCP server: read, and draft CRUD under scopes (MCP-1, MCP-6)."""

from app.interfaces.mcp.catalog import CatalogMcp
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import finish_catalog, make_toolkit
from app.interfaces.mcp.lms.tools import (
    add_block,
    add_question,
    add_staff,
    build_course,
    course_progress,
    create_course,
    create_module,
    create_section,
    create_step,
    delete_block,
    delete_course,
    delete_module,
    delete_question,
    delete_step,
    find_feature,
    generate_course_draft,
    generate_lesson,
    get_attempt,
    get_course,
    get_settings,
    get_step,
    list_attempts,
    list_block_types,
    list_courses,
    list_pending_changes,
    list_staff,
    list_students,
    list_versions,
    move_block,
    move_question,
    move_section,
    move_step,
    override_score,
    publish,
    remove_staff,
    restore_version,
    set_access,
    update_block,
    update_course,
    update_module,
    update_question,
    update_settings,
    update_step,
)
from app.shared.brand import current_brand

from mcp.server.fastmcp import FastMCP

TOOL_MODULES = (
    list_courses,
    find_feature,
    get_course,
    get_step,
    list_block_types,
    list_pending_changes,
    list_versions,
    list_attempts,
    create_course,
    update_course,
    delete_course,
    create_module,
    update_module,
    delete_module,
    create_section,
    create_step,
    update_step,
    delete_step,
    add_block,
    add_question,
    add_staff,
    build_course,
    course_progress,
    delete_block,
    delete_question,
    generate_course_draft,
    generate_lesson,
    get_attempt,
    get_settings,
    list_staff,
    list_students,
    move_block,
    move_question,
    move_section,
    move_step,
    override_score,
    publish,
    remove_staff,
    restore_version,
    update_block,
    update_question,
    update_settings,
    set_access,
)


def build_lms_server(deps: McpDeps) -> FastMCP:
    """Create the LMS Course server with all its tools registered."""
    kit = make_toolkit(
        deps,
        "lms",
        title=f"{current_brand().name} LMS Course",
        instructions_key="mcp-instructions-lms",
        cls=CatalogMcp,
    )
    for module in TOOL_MODULES:
        module.register(kit)
    finish_catalog(kit, "lms", ["find_feature", "list_courses", "get_course"])
    return kit.mcp
