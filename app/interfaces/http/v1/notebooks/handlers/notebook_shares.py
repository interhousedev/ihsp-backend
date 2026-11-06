"""Routes of sharing a notebook: link, people, "shared with me" and attached sets."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks, OwnerActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookItemResponse
from app.interfaces.http.v1.notebooks.schemas_shares import (
    AttachLinkedSetBody,
    JoinShareBody,
    LinkedSetResponse,
    LinkedSetsResponse,
    NotebookSharesResponse,
    SharedNotebookResponse,
    SharedNotebooksResponse,
    ShareLinkResponse,
    ShareRecipientResponse,
    ShareRecipientsResponse,
)

from fastapi import Query


async def get_shares(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> NotebookSharesResponse:
    """Who has access (the owner only)."""
    state = await notebooks.manage_shares.state(actor, notebook_id)
    return NotebookSharesResponse.from_state(state)


async def create_share_link(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> ShareLinkResponse:
    """Create the link or replace its token; the token is shown this once."""
    token = await notebooks.manage_shares.create_link(actor, notebook_id)
    return ShareLinkResponse(token=token)


async def delete_share_link(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> None:
    """Turn the link off and remove everyone who joined through it."""
    await notebooks.manage_shares.delete_link(actor, notebook_id)


async def add_share_person(
    notebook_id: UUID, user_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> None:
    """Give a person read-only access."""
    await notebooks.manage_shares.add_person(actor, notebook_id, user_id)


async def remove_share_person(
    notebook_id: UUID, user_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> None:
    """Revoke a person's access at once and delete their thread."""
    await notebooks.manage_shares.remove_person(actor, notebook_id, user_id)


async def leave_shared(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> None:
    """The recipient removes a shared notebook from their list."""
    await notebooks.manage_shares.leave(actor, notebook_id)


async def join_share(
    body: JoinShareBody, notebooks: Notebooks, actor: OwnerActor
) -> NotebookItemResponse:
    """Open a share link: a signed-in person gets their own grant."""
    notebook = await notebooks.manage_shares.join(actor, body.token)
    return NotebookItemResponse.from_entity(notebook)


async def list_shared(
    notebooks: Notebooks, actor: OwnerActor
) -> SharedNotebooksResponse:
    """The notebooks shared with the caller."""
    found = await notebooks.manage_shares.list_shared(actor)
    return SharedNotebooksResponse(
        items=[SharedNotebookResponse.from_pair(n, name) for n, name in found]
    )


async def search_recipients(
    q: Annotated[str, Query(min_length=3, max_length=100)],
    notebooks: Notebooks,
    actor: OwnerActor,
) -> ShareRecipientsResponse:
    """People to share with, by name (3 letters at least, 10 results at most)."""
    found = await notebooks.manage_shares.search_recipients(actor, q)
    return ShareRecipientsResponse(
        items=[ShareRecipientResponse(id=r.id, name=r.name) for r in found]
    )


async def list_linked_sets(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> LinkedSetsResponse:
    """The sets attached to the caller's notebook."""
    views = await notebooks.linked_sets.list(actor, notebook_id)
    return LinkedSetsResponse(items=[LinkedSetResponse.from_view(v) for v in views])


async def attach_linked_set(
    notebook_id: UUID,
    body: AttachLinkedSetBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> None:
    """Attach a notebook as a live set of sources."""
    await notebooks.linked_sets.attach(actor, notebook_id, body.notebook_id)


async def detach_linked_set(
    notebook_id: UUID, linked_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> None:
    """Detach a set of sources."""
    await notebooks.linked_sets.detach(actor, notebook_id, linked_id)
