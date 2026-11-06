"""Students tool `create_test`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.idempotency import IdempotencyKey, once
from app.interfaces.mcp.student.content_results import test_result
from app.interfaces.mcp.student.test_inputs import NewQuestion, question_dicts
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "tests:write"


def register(kit: ToolKit) -> None:
    """Register `create_test`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("notebook_id",)))
    async def create_test(
        title: Annotated[
            str, Field(min_length=1, max_length=200, description="Name of the test.")
        ],
        questions: Annotated[
            list[NewQuestion],
            Field(min_length=1, max_length=100, description="Questions, 1 to 100."),
        ],
        notebook_id: Annotated[
            UUID | None,
            Field(description="The student's notebook; left out: a default one."),
        ] = None,
        idempotency_key: IdempotencyKey = None,
    ) -> dict[str, Any]:
        """Create a practice test from these questions; no AI budget is spent.

        Each question stands alone: it carries any passage it needs. Prefer showing
        `links.open`.
        """
        actor = current_actor()

        async def create() -> dict[str, Any]:
            found = await kit.deps.content_tools.create_test(
                actor,
                notebook_id=notebook_id,
                title=title,
                questions=question_dicts(questions),
            )
            return test_result(kit.deps, found)

        return await once(
            kit,
            user_id=actor.user_id,
            tool="create_test",
            key=idempotency_key,
            arguments={
                "title": title,
                "notebook_id": notebook_id,
                "questions": question_dicts(questions),
            },
            create=create,
        )
