"""Students tool `batch_edit_test_questions`."""

from typing import Annotated, Any, Final
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.content_results import test_result
from app.interfaces.mcp.student.test_inputs import (
    NewQuestion,
    QuestionChange,
    question_dicts,
)
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "tests:write"
MAX_OPERATIONS: Final = 100
QuestionId = Annotated[str, Field(min_length=1, max_length=40)]


def register(kit: ToolKit) -> None:
    """Register `batch_edit_test_questions`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("test_id",)))
    async def batch_edit_test_questions(
        test_id: Annotated[UUID, Field(description="Test id from list_tests.")],
        add: list[NewQuestion] | None = None,
        update: list[QuestionChange] | None = None,
        delete_ids: list[QuestionId] | None = None,
    ) -> dict[str, Any]:
        """Add, edit and delete questions of one of the student's tests at once.

        All of it applies, or nothing. A test keeps 1 to 100 questions; question ids
        stay stable.
        """
        actor = current_actor()
        new, edits, gone = add or [], update or [], delete_ids or []
        if not 1 <= len(new) + len(edits) + len(gone) <= MAX_OPERATIONS:
            raise McpInvalidInputError(
                params={"reason": f"give 1 to {MAX_OPERATIONS} operations"}
            )
        found = await kit.deps.content_tools.batch_edit_test_questions(
            actor.user_id,
            test_id,
            add=question_dicts(new),
            update=question_dicts(edits),
            delete_ids=gone,
        )
        return test_result(kit.deps, found)
