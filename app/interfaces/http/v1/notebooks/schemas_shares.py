"""Request and response models of notebook sharing (NB-SHARE)."""

from datetime import datetime
from typing import Self
from uuid import UUID

from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookItemResponse
from app.modules.notebooks.application.linked_sets import LinkedSetView
from app.modules.notebooks.application.manage_shares import ShareState
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.sharing import ShareVia

from pydantic import BaseModel, Field

TOKEN_MAX_CHARS = 128


class JoinShareBody(BaseModel):
    """The token of a share link, in the body so that it stays out of access logs."""

    token: str = Field(min_length=1, max_length=TOKEN_MAX_CHARS)


class ShareLinkResponse(BaseModel):
    """A new token: it is shown this once, only its hash is stored."""

    token: str


class SharePersonResponse(BaseModel):
    """A person with access."""

    user_id: UUID
    name: str
    via: ShareVia
    created_at: datetime


class NotebookSharesResponse(BaseModel):
    """Who has access, whether a link works and which kinds of source stay private."""

    link_active: bool
    people: list[SharePersonResponse]
    hidden_source_kinds: list[SourceKind]

    @classmethod
    def from_state(cls, state: ShareState) -> Self:
        """Build from the use case's result."""
        return cls(
            link_active=state.link_active,
            people=[
                SharePersonResponse(
                    user_id=share.user_id,
                    name=name,
                    via=share.via,
                    created_at=share.created_at,
                )
                for share, name in state.people
            ],
            hidden_source_kinds=state.hidden_source_kinds,
        )


class ShareRecipientResponse(BaseModel):
    """A person found by name; never a login or a contact."""

    id: UUID
    name: str


class ShareRecipientsResponse(BaseModel):
    """`{items}` of the people found."""

    items: list[ShareRecipientResponse]


class SharedNotebookResponse(NotebookItemResponse):
    """A notebook shared with the caller."""

    owner_name: str

    @classmethod
    def from_pair(cls, notebook: Notebook, owner_name: str) -> Self:
        """Build from the notebook and the name of its owner."""
        return cls(
            **dict(NotebookItemResponse.from_entity(notebook)), owner_name=owner_name
        )


class SharedNotebooksResponse(BaseModel):
    """`{items}` of the notebooks shared with the caller."""

    items: list[SharedNotebookResponse]


class AttachLinkedSetBody(BaseModel):
    """The notebook to attach as a live set of sources."""

    notebook_id: UUID


class LinkedSetResponse(BaseModel):
    """An attached notebook; only its id once the caller has no access to it."""

    notebook_id: UUID
    available: bool
    title: str | None
    emoji: str | None
    sources: list[SourceItemResponse]

    @classmethod
    def from_view(cls, view: LinkedSetView) -> Self:
        """Build from the use case's result."""
        return cls(
            notebook_id=view.notebook_id,
            available=view.available,
            title=view.title,
            emoji=view.emoji,
            sources=[SourceItemResponse.from_entity(s) for s in view.sources],
        )


class LinkedSetsResponse(BaseModel):
    """`{items}` of the sets attached to a notebook."""

    items: list[LinkedSetResponse]
