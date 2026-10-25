"""Author tool: the Studio outputs of the course workspace."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.application.tools.lms_base import AuthorReadTool
from app.modules.ai.application.tools.lms_common import (
    lms_call,
    notebook_queries_of,
    scope_of,
)
from app.modules.ai.domain.tool_args import ToolArgs


class ListWorkspaceOutputsArgs(ToolArgs):
    """No arguments: the workspace is the chat's course workspace."""


class ListWorkspaceOutputs(AuthorReadTool[ListWorkspaceOutputsArgs]):
    """Course plans, lesson drafts, quizzes and other outputs of the workspace."""

    name = "list_workspace_outputs"
    description = (
        "List the Studio outputs of this course's workspace: id, kind (course_plan, "
        "lesson_draft, quiz, flashcards, report, ...), title and status (queued, "
        "generating, ready, failed). Use it to find the artifact_id for "
        "apply_studio_output or to check whether an output you started is ready. "
        "Only `ready` outputs can be applied. Example: list_workspace_outputs {}"
    )
    args_model = ListWorkspaceOutputsArgs

    async def run(
        self, args: ListWorkspaceOutputsArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the outputs of the scope's workspace."""
        scope = scope_of(ctx)
        rows = await lms_call(
            notebook_queries_of(self.bindings).list_artifacts(
                ctx.actor.user_id, scope.notebook_id
            )
        )
        return capped(rows)
