"""In-memory fake of `McpTeacherTools`: records calls; a foreign group is refused."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError


class FakeTeacherTools:
    """Records every call; only `own_group_ids` belong to the teacher."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.own_group_ids: set[UUID] = set()

    async def group_roster(self, actor: Actor, group_id: UUID) -> dict[str, Any]:
        """The roster of an own group; Forbidden otherwise."""
        self.calls.append(("group_roster", (actor.user_id, group_id)))
        if group_id not in self.own_group_ids:
            raise ForbiddenError("not your group")
        return {"group_id": str(group_id), "students": []}

    def __getattr__(self, name: str) -> Callable[..., Awaitable[dict[str, Any]]]:
        async def record(*args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((name, (*args, *kwargs.values())))
            return {"ok": True}

        return record
