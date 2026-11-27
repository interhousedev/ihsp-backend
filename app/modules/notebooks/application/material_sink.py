"""Store teaching materials as text sources of the subject notebook."""

import hashlib
from typing import Any
from uuid import UUID

from app.modules.notebooks.ports.material_sink import NotebookDirectory, SourceWriter
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.contracts.material_sink import Material
from app.shared.contracts.teaching_scope import TeachingScope


def _identity(material: Material) -> str:
    parts = [material.body_md]
    if material.media_file_id is not None:
        parts.append(str(material.media_file_id))
    parts.extend(f"{s.start_ms}-{s.end_ms}" for s in material.segments)
    return "\x1f".join(parts)


class MaterialSink:
    """Teacher output into the subject (or group) notebook."""

    def __init__(
        self, notebooks: NotebookDirectory, sources: SourceWriter, scope: TeachingScope
    ) -> None:
        """Bind the notebook directory, the source writer and the scope check."""
        self.notebooks = notebooks
        self.sources = sources
        self.scope = scope

    async def authorize(
        self, actor: Actor, subject_id: UUID, group_id: UUID | None
    ) -> None:
        """Refuse students and destinations the actor does not teach."""
        if not (actor.has(Role.TEACHER) or actor.has(Role.ADMIN)):
            raise ForbiddenError(params={"roles": ["teacher", "admin"]})
        if not await self.scope.can_teach(actor, subject_id, group_id):
            raise ForbiddenError(params={"subject_id": str(subject_id)})

    async def store(self, actor: Actor, material: Material) -> Any:
        """Store the material; the same material is stored once."""
        await self.authorize(actor, material.subject_id, material.group_id)
        digest = hashlib.sha256(_identity(material).encode()).hexdigest()
        ref: dict[str, Any] = {}
        origin: dict[str, Any] = {"teacher_ai": material.kind}
        if material.media_file_id is not None:
            ref["media_file_id"] = material.media_file_id
            ref["segments"] = [
                {"start_ms": s.start_ms, "end_ms": s.end_ms} for s in material.segments
            ]
        if material.kind == "work_check":
            origin["sensitive"] = True
            ref["sensitive"] = True
        notebook_id = await self.notebooks.subject_notebook(
            actor.user_id, material.subject_id, material.group_id
        )
        return await self.sources.add_text(
            notebook_id=notebook_id,
            owner_id=actor.user_id,
            title=material.title,
            body_md=material.body_md,
            ref=ref,
            ref_key=f"teacher_ai:{material.kind}:{digest}",
            origin=origin,
        )
