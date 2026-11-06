"""Port: grants, links and attached source sets of notebooks."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.sharing import LinkedSet, NotebookShare, ShareVia


class ShareRepository(Protocol):
    """Sharing rows of the open transaction."""

    async def active(self, notebook_id: UUID, user_id: UUID) -> NotebookShare | None:
        """The person's grant unless it was revoked."""
        ...

    async def find(self, notebook_id: UUID, user_id: UUID) -> NotebookShare | None:
        """The person's row, revoked or not."""
        ...

    async def put(self, share: NotebookShare) -> None:
        """Insert the grant or replace the person's row."""
        ...

    async def revoke(self, notebook_id: UUID, user_id: UUID, now: datetime) -> bool:
        """Mark a live grant revoked; False when there was none."""
        ...

    async def delete(self, notebook_id: UUID, user_id: UUID) -> None:
        """Forget the person's row."""
        ...

    async def delete_via(self, notebook_id: UUID, via: ShareVia) -> list[UUID]:
        """Forget the live grants of one kind; return who lost access."""
        ...

    async def list_active(self, notebook_id: UUID) -> list[NotebookShare]:
        """The live grants of a notebook, oldest first."""
        ...

    async def notebooks_of(self, user_id: UUID) -> list[UUID]:
        """Notebooks shared with the person, newest grant first."""
        ...

    async def delete_for_user(self, user_id: UUID) -> None:
        """Forget every row of a removed account."""
        ...

    async def link_exists(self, notebook_id: UUID) -> bool:
        """True when the notebook has an active link."""
        ...

    async def set_link(self, notebook_id: UUID, token_hash: str, now: datetime) -> None:
        """Create the link or replace its token."""
        ...

    async def delete_link(self, notebook_id: UUID) -> None:
        """Turn the link off."""
        ...

    async def notebook_of_token(self, token_hash: str) -> UUID | None:
        """The notebook of an active link."""
        ...

    async def linked_sets(self, notebook_id: UUID) -> list[LinkedSet]:
        """The sets attached to a notebook, oldest first."""
        ...

    async def add_linked_set(self, linked: LinkedSet) -> None:
        """Attach a set (attaching it again changes nothing)."""
        ...

    async def remove_linked_set(self, notebook_id: UUID, linked_id: UUID) -> None:
        """Detach a set."""
        ...

    async def remove_linked_sets_of(
        self, user_notebooks: Sequence[UUID], linked_id: UUID
    ) -> None:
        """Detach one set from several notebooks."""
        ...
