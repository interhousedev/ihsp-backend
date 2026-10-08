"""Use case: append a question to a test block of a draft step (MCP-6)."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.append_block import parse_content
from app.modules.lms.application.authoring.get_step_draft import GetStepDraft
from app.modules.lms.application.authoring.save_step_draft import SaveStepDraft
from app.modules.lms.domain.authoring.content_edit import with_question_appended
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import DraftConflictError
from app.modules.lms.domain.step_content import StepContent, TestBlock
from app.shared.actor import Actor


class AppendQuestion:
    """Add a question to an existing test block of a draft step."""

    def __init__(self, get_step_draft: GetStepDraft, save: SaveStepDraft) -> None:
        """Store the use cases it composes."""
        self.get_step_draft = get_step_draft
        self.save = save

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question: dict[str, Any],
        *,
        via: StepVia = StepVia.MCP,
    ) -> dict[str, Any]:
        """Append the question; on a version conflict retry once on the new draft."""
        try:
            return await self._attempt(actor, step_id, block_id, question, via)
        except DraftConflictError:
            return await self._attempt(actor, step_id, block_id, question, via)

    async def _attempt(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question: dict[str, Any],
        via: StepVia,
    ) -> dict[str, Any]:
        current = await self.get_step_draft.execute(actor, step_id)
        raw = current.content.model_dump(mode="json")
        content = parse_content(with_question_appended(raw, block_id, question))
        saved = await self.save.execute(
            actor, step_id, content, current.lock_version, via=via
        )
        return {
            "step_id": str(step_id),
            "block_id": block_id,
            "question_id": _last_question_id(saved.content, block_id),
            "lock_version": saved.lock_version,
        }


def _last_question_id(content: StepContent, block_id: str) -> str | None:
    for block in content.blocks:
        if block.id == block_id and isinstance(block, TestBlock) and block.questions:
            return block.questions[-1].id
    return None
