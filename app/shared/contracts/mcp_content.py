"""What the content MCP tools need (implemented in bootstrap/adapters/mcp_content.py).

Flash cards, tests (notebook quiz artifacts, D1), notebooks, library and knowledge. The
actor comes from the guard. Someone else's object raises a NotFoundError. A notebook
shared with the user is not opened here: recipients use their own permitted paths.
"""

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class McpContentTools(Protocol):
    """The content tools of the Students server."""

    async def batch_edit_cards(
        self,
        user_id: UUID,
        set_id: UUID,
        *,
        add: Sequence[dict[str, Any]],
        update: Sequence[dict[str, Any]],
        delete_ids: Sequence[UUID],
    ) -> dict[str, Any]:
        """Apply all changes in one transaction, or none; a foreign id fails all."""
        ...

    async def list_tests(self, user_id: UUID, *, limit: int) -> list[dict[str, Any]]:
        """Quiz artifacts this user owns."""
        ...

    async def get_test(self, user_id: UUID, test_id: UUID) -> dict[str, Any]:
        """The owner's quiz with its answers; never a shared one."""
        ...

    async def create_test(
        self,
        actor: Actor,
        *,
        notebook_id: UUID | None,
        title: str,
        questions: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a quiz from given questions, with no model call."""
        ...

    async def batch_edit_test_questions(
        self,
        user_id: UUID,
        test_id: UUID,
        *,
        add: Sequence[dict[str, Any]],
        update: Sequence[dict[str, Any]],
        delete_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Validate and apply all question changes in one transaction."""
        ...

    async def search_knowledge(
        self, query: str, *, audience: str, limit: int
    ) -> list[dict[str, Any]]:
        """Knowledge hits for an audience derived from the server, not the client."""
        ...

    async def list_notebooks(self, actor: Actor) -> list[dict[str, Any]]:
        """Notebooks readable by the actor, without hidden flash card notebooks."""
        ...

    async def get_notebook(self, actor: Actor, notebook_id: UUID) -> dict[str, Any]:
        """One readable notebook with its sources and outputs."""
        ...

    async def search_notebooks(
        self, actor: Actor, query: str, *, notebook_id: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        """Passages from one notebook, or the most recently opened ones."""
        ...

    async def read_notebook_source(
        self, actor: Actor, notebook_id: UUID, source_id: UUID, *, page: int
    ) -> dict[str, Any]:
        """One bounded page of a source's text."""
        ...

    async def list_notebook_outputs(
        self, actor: Actor, notebook_id: UUID
    ) -> list[dict[str, Any]]:
        """Studio artifacts of a readable notebook."""
        ...

    async def create_notebook(self, actor: Actor, title: str) -> dict[str, Any]:
        """Create a personal notebook."""
        ...

    async def add_notebook_sources(
        self,
        actor: Actor,
        notebook_id: UUID,
        *,
        file_ids: Sequence[UUID],
        texts: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add sources from the user's files and given text; no URL in this round."""
        ...

    async def generate_notebook_output(
        self,
        actor: Actor,
        notebook_id: UUID,
        *,
        kind: str,
        options: dict[str, Any],
        focus: str | None,
    ) -> dict[str, Any]:
        """Request an artifact under the normal budget and AI access guard (D9)."""
        ...

    async def search_library(
        self, actor: Actor, query: str, *, limit: int
    ) -> list[dict[str, Any]]:
        """Library items visible to the actor; never the external UniLibrary source."""
        ...

    async def get_library_item(self, actor: Actor, item_id: UUID) -> dict[str, Any]:
        """A visible library item."""
        ...

    async def read_library_text(
        self, actor: Actor, item_id: UUID, *, page: int
    ) -> dict[str, Any]:
        """One bounded page of a visible item's text."""
        ...
