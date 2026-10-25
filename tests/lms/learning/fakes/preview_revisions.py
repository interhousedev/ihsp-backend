"""Fake of the authoring side's `ensure_preview_revision` port."""

from uuid import UUID

from app.shared.actor import Actor


class FakePreviewRevisions:
    """Returns revisions that tests created ahead of time, per step."""

    def __init__(self) -> None:
        self.revisions: dict[UUID, UUID] = {}
        self.calls: list[tuple[UUID, UUID]] = []

    async def ensure_preview_revision(self, step_id: UUID, actor: Actor) -> UUID:
        """Record the call and return the prepared revision of the step."""
        self.calls.append((step_id, actor.user_id))
        return self.revisions[step_id]
