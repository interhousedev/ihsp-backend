"""Request and response models of the source and passage endpoints (§ 4.4)."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from app.interfaces.http.errors import problem_body
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse
from app.modules.notebooks.application.views import AddSourcesResult, PassageDetailView
from app.modules.notebooks.domain.entities import Citation, Passage, Source, SourceGuide
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.limits import SOURCE_TITLE_MAX_CHARS
from app.modules.notebooks.domain.source_input import SourceInput
from app.shared.contracts.files import FileRef

from fastapi import Request
from pydantic import BaseModel, Field

BATCH_MAX = 20  # § 4.3; the configured `add_batch_max` is checked by the use case


class AddSourcesBody(BaseModel):
    """POST /v1/notebooks/{id}/sources: 1 to 20 items, each of its own `kind`."""

    items: list[SourceInput] = Field(min_length=1, max_length=BATCH_MAX)


class SelectSourcesBody(BaseModel):
    """POST /v1/notebooks/{id}/sources/select: every source when `ids` is absent."""

    selected: bool
    ids: list[UUID] | None = None


class UpdateSourceBody(BaseModel):
    """PATCH /v1/notebooks/{id}/sources/{sid}: only the keys that were sent apply."""

    title: str | None = Field(default=None, max_length=SOURCE_TITLE_MAX_CHARS)
    selected: bool | None = None
    body_md: str | None = None


class SourceFileResponse(BaseModel):
    """`SourceFile`: the uploaded file behind a source (preview and download)."""

    id: UUID
    name: str
    content_type: str
    byte_size: int

    @classmethod
    def from_ref(cls, ref: FileRef) -> Self:
        """Build from the files contract."""
        return cls(
            id=ref.id,
            name=ref.name,
            content_type=ref.content_type,
            byte_size=ref.byte_size,
        )


class SourceFileUrlResponse(BaseModel):
    """`SourceFileUrl`: a presigned URL of the file behind a source (60 seconds)."""

    url: str
    expires_at: datetime


class SourceDetailResponse(SourceItemResponse):
    """`SourceDetail`: the item plus guide, text of a note, cited passages and file."""

    guide: SourceGuide | None
    body_md: str | None
    editable: bool
    citations: list[Citation]
    file: SourceFileResponse | None = None
    """The uploaded file behind a `file` source or a file-based lesson material
    (`GET …/file-url` gives a link to it); null for every other source."""

    @classmethod
    def from_entity(cls, source: Source, file: FileRef | None = None) -> Self:
        """Build from the source entity and, when there is one, its file."""
        return cls(
            **dict(SourceItemResponse.from_entity(source)),
            guide=source.guide,
            body_md=source.body_md,
            editable=source.editable,
            citations=source.citations or [],
            file=None if file is None else SourceFileResponse.from_ref(file),
        )


class ProblemResponse(BaseModel):
    """The body of a problem+json response, as it is also nested in `rejected`."""

    type: str
    title: str
    status: int
    message_key: str
    params: dict[str, Any]


class RejectedSourceResponse(BaseModel):
    """An item of the request that was not added: its position and the reason."""

    index: int
    error: ProblemResponse


class AddSourcesResponse(BaseModel):
    """`AddSourcesResult`: the stored sources and the items that were refused."""

    items: list[SourceItemResponse]
    rejected: list[RejectedSourceResponse]

    @classmethod
    def from_result(cls, result: AddSourcesResult, request: Request) -> Self:
        """Build from the use case result; each error is a problem+json body."""
        return cls(
            items=[SourceItemResponse.from_entity(s) for s in result.items],
            rejected=[
                RejectedSourceResponse(
                    index=item.index,
                    error=ProblemResponse.model_validate(
                        problem_body(request, item.error)
                    ),
                )
                for item in result.rejected
            ],
        )


class PassageItemResponse(BaseModel):
    """`PassageItem`."""

    id: UUID
    seq: int
    text: str
    page: int | None
    heading: str | None

    @classmethod
    def from_entity(cls, passage: Passage) -> Self:
        """Build from the passage entity."""
        return cls(
            id=passage.id,
            seq=passage.seq,
            text=passage.text,
            page=passage.page,
            heading=passage.heading,
        )


class PassageSourceResponse(BaseModel):
    """The source a passage belongs to (id, title, kind)."""

    id: UUID
    title: str
    kind: SourceKind


class PassageDetailResponse(BaseModel):
    """`PassageDetail`: a passage with the passages before and after it."""

    passage: PassageItemResponse
    source: PassageSourceResponse
    before: list[PassageItemResponse]
    after: list[PassageItemResponse]

    @classmethod
    def from_view(cls, view: PassageDetailView) -> Self:
        """Build from the use case view."""
        return cls(
            passage=PassageItemResponse.from_entity(view.passage),
            source=PassageSourceResponse(
                id=view.source.id, title=view.source.title, kind=view.source.kind
            ),
            before=[PassageItemResponse.from_entity(p) for p in view.before],
            after=[PassageItemResponse.from_entity(p) for p in view.after],
        )
