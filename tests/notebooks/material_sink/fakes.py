"""In-memory notebook directory and source writer for the material sink."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.shared.actor import Actor, Role
from app.shared.ids import new_id


class FakeNotebooks:
    """`NotebookDirectory`: finds or creates the teacher's subject notebook."""

    def __init__(self) -> None:
        self.notebooks: dict[tuple[UUID, UUID, UUID | None], UUID] = {}

    async def subject_notebook(
        self, owner_id: Any, subject_id: Any, group_id: Any
    ) -> Any:
        key = (owner_id, subject_id, group_id)
        return self.notebooks.setdefault(key, new_id())


class FakeSources:
    """`SourceWriter`: keeps text sources, unique by (notebook, ref_key)."""

    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []

    async def add_text(
        self,
        *,
        notebook_id: Any,
        owner_id: Any,
        title: Any,
        body_md: Any,
        ref: Any,
        ref_key: Any,
        origin: Any,
    ) -> Any:
        for row in self.rows:
            if (row.notebook_id, row.ref_key) == (notebook_id, ref_key):
                return row
        row = SimpleNamespace(
            id=new_id(),
            notebook_id=notebook_id,
            owner_id=owner_id,
            title=title,
            body_md=body_md,
            ref=ref,
            ref_key=ref_key,
            origin=origin,
        )
        self.rows.append(row)
        return row


class FakeScope:
    """`TeachingScope`: (subject, group) pairs each teacher currently teaches.

    The real one reads `TeachingDirectory` (current term, subgroup aware, expired
    assignments excluded); admins pass. A `None` group means "the subject as a whole".
    """

    def __init__(self) -> None:
        self.grants: set[tuple[UUID, UUID, UUID | None]] = set()

    def allow(self, actor: Actor, subject_id: Any, group_id: Any = None) -> None:
        self.grants.add((actor.user_id, subject_id, group_id))

    async def can_teach(self, actor: Actor, subject_id: Any, group_id: Any) -> bool:
        if Role.ADMIN in actor.roles:
            return True
        return (actor.user_id, subject_id, group_id) in self.grants
