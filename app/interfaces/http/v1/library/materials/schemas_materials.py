"""Requests and responses of the materials endpoints (names follow doc § 7.5)."""

from typing import Annotated, Self
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import (
    BookSubjectInput,
    BookTopicInput,
)
from app.interfaces.http.v1.library.catalogue.schemas_items import ItemCardSchema
from app.modules.library.application.materials.inputs import MaterialData, MaterialPatch
from app.modules.library.application.materials.views import UploadRowView
from app.modules.library.domain.enums import (
    ItemLanguage,
    ItemStatus,
    ItemType,
    MaterialLicence,
    ReportReason,
    StatusReasonCode,
)

from pydantic import BaseModel, Field

YearOfStudy = Annotated[int, Field(ge=1, le=12)]
BODY_MAX_CHARS = 2_000_000


class MaterialInputBody(BaseModel):
    """`MaterialInput`: the upload form; `attested` may be false until submit."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=2000)
    subject_ids: list[UUID] = Field(max_length=20)
    topic_ids: list[UUID] = Field(default_factory=list, max_length=50)
    years_of_study: list[YearOfStudy] = Field(default_factory=list, max_length=12)
    type: ItemType
    language: ItemLanguage
    licence: MaterialLicence
    body_md: str | None = Field(default=None, max_length=BODY_MAX_CHARS)
    attested: bool

    def to_data(self) -> MaterialData:
        """The use-case input."""
        return MaterialData(
            title=self.title,
            description=self.description,
            subject_ids=tuple(self.subject_ids),
            topic_ids=tuple(self.topic_ids),
            years_of_study=tuple(self.years_of_study),
            type=self.type,
            language=self.language,
            licence=self.licence,
            attested=self.attested,
            body_md=self.body_md,
        )


class MaterialFilesBody(BaseModel):
    """`POST /library/materials/{id}/files`: ids of files uploaded for the material."""

    file_ids: list[UUID] = Field(min_length=1, max_length=25)


class MaterialPatchBody(BaseModel):
    """`PATCH /library/materials/{id}`: only the keys that were sent are applied."""

    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    topic_ids: list[UUID] | None = Field(default=None, max_length=50)
    body_md: str | None = Field(default=None, max_length=BODY_MAX_CHARS)
    attested: bool | None = None

    def to_patch(self) -> MaterialPatch:
        """The use-case input."""
        return MaterialPatch(
            title=self.title,
            description=self.description,
            topic_ids=None if self.topic_ids is None else tuple(self.topic_ids),
            body_md=self.body_md,
            attested=self.attested,
        )


class UploadRowResponse(BaseModel):
    """`UploadRow`: a material of the caller with its status and queue position."""

    item: ItemCardSchema
    status: ItemStatus
    reason: StatusReasonCode | str | None
    review_message: str | None
    queue_position: int | None

    @classmethod
    def from_view(cls, view: UploadRowView) -> Self:
        """Build from the read model."""
        return cls(
            item=ItemCardSchema.from_view(view.item),
            status=view.status,
            reason=view.reason,
            review_message=view.review_message,
            queue_position=view.queue_position,
        )


class UploadsParams(BaseModel):
    """`GET /me/library/uploads` query string."""

    status: ItemStatus | None = None
    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)


class SuggestedBookBody(BaseModel):
    """`SuggestedBook`: the book form without the librarian-only fields."""

    title: str = Field(min_length=1, max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)
    authors: list[str] = Field(default_factory=list, max_length=20)
    translators: list[str] = Field(default_factory=list, max_length=20)
    language: ItemLanguage
    year_published: int | None = Field(default=None, ge=-3000, le=2200)
    publisher: str | None = Field(default=None, max_length=255)
    isbn: str | None = Field(default=None, max_length=32)
    type: ItemType
    description: str | None = Field(default=None, max_length=2000)
    years_of_study: list[int] = Field(default_factory=list, max_length=4)
    subjects: list[BookSubjectInput] = Field(default_factory=list, max_length=20)
    topics: list[BookTopicInput] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    cover_file_id: UUID | None = None


class SuggestionBody(BaseModel):
    """`POST /library/suggestions`: a title and, from the editor, the whole form."""

    title: str = Field(min_length=1, max_length=255)
    url: str | None = Field(default=None, max_length=2000)
    file_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)
    book: SuggestedBookBody | None = None


class LibraryReportBody(BaseModel):
    """`POST /library/items/{id}/report`."""

    reason: ReportReason
    text: str | None = Field(default=None, max_length=500)
