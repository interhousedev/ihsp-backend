"""Fake of McpContentTools: objects by owner, every call recorded."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.interfaces.mcp.errors import McpNotFoundError
from app.shared.actor import Actor
from app.shared.ids import new_id


class FakeContentTools:
    """Sets, tests and notebooks belong to users; anything else is not found."""

    def __init__(self) -> None:
        self.sets: dict[UUID, UUID] = {}
        self.tests: dict[UUID, dict[str, Any]] = {}
        self.notebooks: dict[UUID, UUID] = {}
        self.items: dict[UUID, dict[str, Any]] = {}
        self.knowledge: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, name: str, **arguments: Any) -> None:
        self.calls.append((name, arguments))

    def _own_notebook(self, actor: Actor, notebook_id: UUID) -> None:
        if self.notebooks.get(notebook_id) != actor.user_id:
            raise McpNotFoundError()

    async def batch_edit_cards(
        self,
        user_id: UUID,
        set_id: UUID,
        *,
        add: Sequence[dict[str, Any]],
        update: Sequence[dict[str, Any]],
        delete_ids: Sequence[UUID],
    ) -> dict[str, Any]:
        if self.sets.get(set_id) != user_id:
            raise McpNotFoundError()
        self._record("batch_edit_cards", add=add, update=update, delete_ids=delete_ids)
        return {"id": set_id, "title": "Set", "cards": []}

    async def list_tests(self, user_id: UUID, *, limit: int) -> list[dict[str, Any]]:
        return [
            {key: test[key] for key in ("id", "notebook_id", "title")}
            for test in self.tests.values()
            if test["owner"] == user_id
        ][:limit]

    async def get_test(self, user_id: UUID, test_id: UUID) -> dict[str, Any]:
        test = self.tests.get(test_id)
        if test is None or test["owner"] != user_id:
            raise McpNotFoundError()
        return {k: v for k, v in test.items() if k != "owner"}

    async def create_test(
        self,
        actor: Actor,
        *,
        notebook_id: UUID | None,
        title: str,
        questions: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        if notebook_id is not None:
            self._own_notebook(actor, notebook_id)
        test_id = new_id()
        self.tests[test_id] = {
            "id": test_id,
            "notebook_id": notebook_id or new_id(),
            "title": title,
            "questions": list(questions),
            "owner": actor.user_id,
        }
        return await self.get_test(actor.user_id, test_id)

    async def batch_edit_test_questions(
        self,
        user_id: UUID,
        test_id: UUID,
        *,
        add: Sequence[dict[str, Any]],
        update: Sequence[dict[str, Any]],
        delete_ids: Sequence[str],
    ) -> dict[str, Any]:
        found = await self.get_test(user_id, test_id)
        self._record("edit_test", add=add, update=update, delete_ids=delete_ids)
        return found

    async def search_knowledge(
        self, query: str, *, audience: str, limit: int
    ) -> list[dict[str, Any]]:
        self._record("search_knowledge", query=query, audience=audience, limit=limit)
        return self.knowledge.get(audience, [])[:limit]

    async def list_notebooks(self, actor: Actor) -> list[dict[str, Any]]:
        return [
            {"id": notebook_id, "title": "NB"}
            for notebook_id, owner in self.notebooks.items()
            if owner == actor.user_id
        ]

    async def get_notebook(self, actor: Actor, notebook_id: UUID) -> dict[str, Any]:
        self._own_notebook(actor, notebook_id)
        return {"id": notebook_id, "title": "NB", "sources": [], "outputs": []}

    async def search_notebooks(
        self, actor: Actor, query: str, *, notebook_id: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        if notebook_id is None:
            return []
        self._own_notebook(actor, notebook_id)
        return [
            {
                "notebook_id": notebook_id,
                "source_title": "S",
                "text": "pas​sage",
            }
        ][:limit]

    async def read_notebook_source(
        self, actor: Actor, notebook_id: UUID, source_id: UUID, *, page: int
    ) -> dict[str, Any]:
        self._own_notebook(actor, notebook_id)
        return {"page": page, "pages": 1, "text": "text"}

    async def list_notebook_outputs(
        self, actor: Actor, notebook_id: UUID
    ) -> list[dict[str, Any]]:
        self._own_notebook(actor, notebook_id)
        return [{"id": new_id(), "kind": "quiz", "title": "Q", "status": "ready"}]

    async def create_notebook(self, actor: Actor, title: str) -> dict[str, Any]:
        notebook_id = new_id()
        self.notebooks[notebook_id] = actor.user_id
        return {"id": notebook_id, "title": title}

    async def add_notebook_sources(
        self,
        actor: Actor,
        notebook_id: UUID,
        *,
        file_ids: Sequence[UUID],
        texts: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        self._own_notebook(actor, notebook_id)
        self._record("add_sources", file_ids=file_ids, texts=texts)
        return {"notebook_id": notebook_id, "sources": []}

    async def generate_notebook_output(
        self,
        actor: Actor,
        notebook_id: UUID,
        *,
        kind: str,
        options: dict[str, Any],
        focus: str | None,
    ) -> dict[str, Any]:
        self._own_notebook(actor, notebook_id)
        self._record("generate", kind=kind, options=options, focus=focus)
        return {"id": new_id(), "kind": kind, "status": "queued"}

    async def search_library(
        self, actor: Actor, query: str, *, limit: int
    ) -> list[dict[str, Any]]:
        return list(self.items.values())[:limit]

    async def get_library_item(self, actor: Actor, item_id: UUID) -> dict[str, Any]:
        if item_id not in self.items:
            raise McpNotFoundError()
        return self.items[item_id]

    async def read_library_text(
        self, actor: Actor, item_id: UUID, *, page: int
    ) -> dict[str, Any]:
        found = await self.get_library_item(actor, item_id)
        return {"id": item_id, "title": found["title"], "page": page, "text": "body"}
