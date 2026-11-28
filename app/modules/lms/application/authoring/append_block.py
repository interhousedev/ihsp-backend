"""Use case: append a block to a step draft, for MCP clients (MCP-6, LMS-22)."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.get_step_draft import GetStepDraft
from app.modules.lms.application.authoring.save_step_draft import SaveStepDraft
from app.modules.lms.domain.authoring.content_edit import with_block_appended
from app.modules.lms.domain.authoring.enums import StepVia
from app.modules.lms.domain.authoring.errors import (
    ContentInvalidError,
    DraftConflictError,
)
from app.modules.lms.domain.step_content import StepContent
from app.shared.actor import Actor

from pydantic import ValidationError


def parse_content(data: dict[str, Any]) -> StepContent:
    """Validate step content built by an add-only edit."""
    try:
        return StepContent.model_validate(data)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise ContentInvalidError(params={"errors": errors}) from exc


class AppendBlock:
    """Add a block at the end of a draft step; never touches published content."""

    def __init__(self, get_step_draft: GetStepDraft, save: SaveStepDraft) -> None:
        """Store the use cases it composes."""
        self.get_step_draft = get_step_draft
        self.save = save

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        block: dict[str, Any],
        *,
        via: StepVia = StepVia.MCP,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Add the block; on a version conflict retry once on the new draft."""
        try:
            return await self._attempt(actor, step_id, block, via, position)
        except DraftConflictError:
            return await self._attempt(actor, step_id, block, via, position)

    async def _attempt(
        self,
        actor: Actor,
        step_id: UUID,
        block: dict[str, Any],
        via: StepVia,
        position: int | None,
    ) -> dict[str, Any]:
        current = await self.get_step_draft.execute(actor, step_id)
        raw = current.content.model_dump(mode="json")
        content = parse_content(with_block_appended(raw, block, position))
        saved = await self.save.execute(
            actor, step_id, content, current.lock_version, via=via
        )
        blocks = saved.content.blocks
        index = len(blocks) - 1 if position is None else min(position, len(blocks) - 1)
        return {
            "step_id": str(step_id),
            "block_id": blocks[index].id,
            "blocks": len(blocks),
            "lock_version": saved.lock_version,
        }
