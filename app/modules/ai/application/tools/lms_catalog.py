"""The course author assistant's tools in their fixed order (reads, then writes)."""

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import Tool
from app.modules.ai.application.tools.lms_add_flashcards_block import (
    AddFlashcardsBlock,
)
from app.modules.ai.application.tools.lms_add_test_block import AddTestBlock
from app.modules.ai.application.tools.lms_add_text_block import AddTextBlock
from app.modules.ai.application.tools.lms_apply_outline import ApplyOutline
from app.modules.ai.application.tools.lms_apply_studio_output import (
    ApplyStudioOutput,
)
from app.modules.ai.application.tools.lms_create_section import CreateSection
from app.modules.ai.application.tools.lms_create_step import CreateStep
from app.modules.ai.application.tools.lms_generate_studio_output import (
    GenerateStudioOutput,
)
from app.modules.ai.application.tools.lms_get_course_outline import GetCourseOutline
from app.modules.ai.application.tools.lms_get_step_draft import GetStepDraft
from app.modules.ai.application.tools.lms_list_workspace_outputs import (
    ListWorkspaceOutputs,
)
from app.modules.ai.application.tools.lms_list_workspace_sources import (
    ListWorkspaceSources,
)
from app.modules.ai.application.tools.lms_read_workspace_source import (
    ReadWorkspaceSource,
)
from app.modules.ai.application.tools.lms_replace_step_content import (
    ReplaceStepContent,
)
from app.modules.ai.application.tools.lms_search_workspace import SearchWorkspace
from app.shared.i18n.core import I18nCore

AUTHOR_READ_TOOLS = (
    "get_course_outline",
    "get_step_draft",
    "list_workspace_sources",
    "search_workspace",
    "read_workspace_source",
    "list_workspace_outputs",
)
AUTHOR_WRITE_TOOLS = (
    "apply_outline",
    "create_section",
    "create_step",
    "replace_step_content",
    "add_text_block",
    "add_test_block",
    "add_flashcards_block",
    "generate_studio_output",
    "apply_studio_output",
)


def make_author_tools(bindings: LateBindings, i18n: I18nCore) -> list[Tool]:
    """Return the course author assistant's tools (AUTHOR_READ_TOOLS, then writes).

    Every tool acts on the course and workspace of the chat's scope; nothing can
    publish, delete or reorder.
    """
    return [
        GetCourseOutline(bindings),
        GetStepDraft(bindings),
        ListWorkspaceSources(bindings),
        SearchWorkspace(bindings),
        ReadWorkspaceSource(bindings),
        ListWorkspaceOutputs(bindings),
        ApplyOutline(bindings, i18n),
        CreateSection(bindings, i18n),
        CreateStep(bindings, i18n),
        ReplaceStepContent(bindings, i18n),
        AddTextBlock(bindings, i18n),
        AddTestBlock(bindings, i18n),
        AddFlashcardsBlock(bindings, i18n),
        GenerateStudioOutput(bindings, i18n),
        ApplyStudioOutput(bindings, i18n),
    ]
