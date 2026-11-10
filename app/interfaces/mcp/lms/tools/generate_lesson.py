"""LMS Course tool `generate_lesson`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.lms_blocks import (
    BlockInputError,
    StepDraftInput,
    build_step_content,
)
from app.shared.lms_scopes import MODULES_WRITE

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `generate_lesson`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("step_id", "apply")))
    async def generate_lesson(
        topic: Annotated[str, Field(min_length=3, max_length=300)],
        language: Annotated[str, Field(pattern=r"^(uz|ru|en)$")] = "en",
        guidance: Annotated[str, Field(max_length=2000)] = "",
        step_id: Annotated[
            UUID | None,
            Field(description="With apply=true: step whose blocks are replaced."),
        ] = None,
        apply: Annotated[
            bool, Field(description="True saves the draft blocks into step_id.")
        ] = False,
    ) -> dict[str, Any]:
        """Draft the blocks of one lesson with the platform AI; optionally save.

        Returns title and blocks. With apply=true and step_id the blocks replace
        the content of that step draft (a pending change; nothing is published).
        """
        actor = current_actor()
        ai = kit.deps.lms_ai
        if ai is None:
            raise ToolError(
                "AI drafting is not available on this server; write the blocks "
                "yourself with add_text_block and add_test_block."
            )
        if apply:
            if step_id is None:
                raise ToolError("apply=true needs step_id; see get_course.")
            await ensure_step(kit, actor, step_id)
        draft = await ai.lesson(
            actor, topic=topic, language=language, guidance=guidance
        )
        if apply and step_id is not None:
            try:
                content = build_step_content(StepDraftInput.model_validate(draft))
            except BlockInputError as exc:
                raise ToolError(f"The draft is invalid: {exc}. Try again.") from exc
            await kit.deps.lms_commands.update_step(
                actor, step_id, title=None, blocks=content["blocks"]
            )
        return {"lesson": draft}
