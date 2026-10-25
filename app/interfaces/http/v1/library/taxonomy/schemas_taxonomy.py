"""Topics, collections and statistics of the TypeScript contract (web `library.ts`)."""

from datetime import date
from typing import Annotated, Self, TypeVar
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import (
    ItemCardSchema,
    SubjectRefSchema,
)
from app.modules.library.application.taxonomy.views import (
    CollectionDetailView,
    CollectionView,
    LibraryStatsView,
    ManageCollectionView,
    ManageSubjectView,
    ManageTopicView,
    SearchMissView,
    TopicView,
    TopItemView,
    UploadDayView,
)
from app.modules.library.domain.enums import ItemStatus, ReportReason
from app.modules.library.domain.taxonomy_unset import UNSET, Unset

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(max_length=200)]
T = TypeVar("T")


def sent(body: BaseModel, name: str, value: T) -> T | Unset:
    """The value when the PATCH sent the field, else the "not sent" marker."""
    return value if name in body.model_fields_set else UNSET


class NamesBody(BaseModel):
    """Names in the three languages of the lyceum."""

    model_config = ConfigDict(extra="forbid")

    uz: Name = ""
    ru: Name = ""
    en: Name = ""

    def to_dict(self) -> dict[str, str]:
        """`{uz, ru, en}` for the use cases."""
        return {"uz": self.uz, "ru": self.ru, "en": self.en}


class NamesResponse(BaseModel):
    """The three names of a topic, collection title or description."""

    uz: str = ""
    ru: str = ""
    en: str = ""

    @classmethod
    def from_names(cls, names: dict[str, str]) -> Self:
        """Missing languages are empty strings."""
        return cls(
            uz=names.get("uz", ""), ru=names.get("ru", ""), en=names.get("en", "")
        )


# - - - Topics - - -


class TopicResponse(BaseModel):
    """`Topic`: a node of the tree of one subject."""

    id: UUID
    subject_id: UUID
    name: str
    slug: str
    year_of_study: int | None
    children: list["TopicResponse"]

    @classmethod
    def from_view(cls, view: TopicView) -> Self:
        """Map the read model with its children."""
        return cls(
            id=view.id,
            subject_id=view.subject_id,
            name=view.name,
            slug=view.slug,
            year_of_study=view.year_of_study,
            children=[cls.from_view(child) for child in view.children],
        )


class ManageTopicResponse(BaseModel):
    """`ManageTopic`: all three names, for the editor."""

    id: UUID
    subject_id: UUID
    parent_id: UUID | None
    name: NamesResponse
    slug: str
    position: int
    year_of_study: int | None
    code: str | None = None
    archived: bool = False

    @classmethod
    def from_view(cls, view: ManageTopicView) -> Self:
        """Map the read model."""
        return cls(
            id=view.id,
            subject_id=view.subject_id,
            parent_id=view.parent_id,
            name=NamesResponse.from_names(view.name),
            slug=view.slug,
            position=view.position,
            year_of_study=view.year_of_study,
            code=view.code,
            archived=view.archived,
        )


class CreateTopicBody(BaseModel):
    """`TopicInput`."""

    model_config = ConfigDict(extra="forbid")

    subject_id: UUID
    name: NamesBody
    parent_id: UUID | None = None
    slug: Annotated[str, StringConstraints(max_length=80)] | None = None
    year_of_study: Annotated[int, Field(ge=1, le=4)] | None = None
    code: Annotated[str, StringConstraints(max_length=40)] | None = None


class UpdateTopicBody(BaseModel):
    """`Partial<TopicInput>`: only the keys that were sent are applied."""

    model_config = ConfigDict(extra="forbid")

    subject_id: UUID | None = None
    name: NamesBody | None = None
    parent_id: UUID | None = None
    slug: Annotated[str, StringConstraints(max_length=80)] | None = None
    year_of_study: Annotated[int, Field(ge=1, le=4)] | None = None
    code: Annotated[str, StringConstraints(max_length=40)] | None = None
    archived: bool | None = None
    position: Annotated[int, Field(ge=0, le=10000)] | None = None


# - - - Subjects - - -


class ManageSubjectResponse(BaseModel):
    """`ManageSubject`: a node of the librarian's subject tree (flat, `parent_id`)."""

    id: UUID
    parent_id: UUID | None
    name: NamesResponse
    slug: str
    code: str | None
    position: int
    archived: bool

    @classmethod
    def from_view(cls, view: ManageSubjectView) -> Self:
        """Map the read model."""
        return cls(
            id=view.id,
            parent_id=view.parent_id,
            name=NamesResponse.from_names(view.name),
            slug=view.slug,
            code=view.code,
            position=view.position,
            archived=view.archived,
        )


class CreateSubjectBody(BaseModel):
    """`SubjectInput`."""

    model_config = ConfigDict(extra="forbid")

    name: NamesBody
    parent_id: UUID | None = None
    code: Annotated[str, StringConstraints(max_length=40)] | None = None
    slug: Annotated[str, StringConstraints(max_length=80)] | None = None


class UpdateSubjectBody(BaseModel):
    """`Partial<SubjectInput>` with the archive flag and the position among siblings."""

    model_config = ConfigDict(extra="forbid")

    name: NamesBody | None = None
    parent_id: UUID | None = None
    code: Annotated[str, StringConstraints(max_length=40)] | None = None
    slug: Annotated[str, StringConstraints(max_length=80)] | None = None
    archived: bool | None = None
    position: Annotated[int, Field(ge=0, le=10000)] | None = None


# - - - Collections - - -


class CollectionResponse(BaseModel):
    """`Collection` in the reader's language."""

    id: UUID
    slug: str
    title: str
    description: str | None
    cover_url: str | None
    item_count: int

    @classmethod
    def from_view(cls, view: CollectionView) -> Self:
        """Map the read model."""
        return cls(
            id=view.id,
            slug=view.slug,
            title=view.title,
            description=view.description,
            cover_url=view.cover_url,
            item_count=view.item_count,
        )


class CollectionDetailResponse(CollectionResponse):
    """`CollectionDetail`: the collection and the cards the viewer may see."""

    items: list[ItemCardSchema]

    @classmethod
    def from_detail(cls, view: CollectionDetailView) -> Self:
        """Map the read model."""
        base = view.collection
        return cls(
            id=base.id,
            slug=base.slug,
            title=base.title,
            description=base.description,
            cover_url=base.cover_url,
            item_count=base.item_count,
            items=[ItemCardSchema.from_view(card) for card in view.items],
        )


class ManageCollectionResponse(BaseModel):
    """`ManageCollection`: all languages and the stored item ids."""

    id: UUID
    slug: str
    title: NamesResponse
    description: NamesResponse | None
    cover_url: str | None
    published: bool
    position: int
    item_ids: list[UUID]

    @classmethod
    def from_view(cls, view: ManageCollectionView) -> Self:
        """Map the read model."""
        return cls(
            id=view.id,
            slug=view.slug,
            title=NamesResponse.from_names(view.title),
            description=(
                NamesResponse.from_names(view.description)
                if view.description is not None
                else None
            ),
            cover_url=view.cover_url,
            published=view.published,
            position=view.position,
            item_ids=list(view.item_ids),
        )


class CreateCollectionBody(BaseModel):
    """`CollectionInput`."""

    model_config = ConfigDict(extra="forbid")

    title: NamesBody
    published: bool
    description: NamesBody | None = None
    cover_file_id: UUID | None = None
    item_ids: list[UUID] = Field(default_factory=list)


class UpdateCollectionBody(BaseModel):
    """`Partial<CollectionInput>`: only the keys that were sent are applied."""

    model_config = ConfigDict(extra="forbid")

    title: NamesBody | None = None
    published: bool | None = None
    description: NamesBody | None = None
    cover_file_id: UUID | None = None
    item_ids: list[UUID] | None = None


# - - - Statistics - - -


class QueueStatsResponse(BaseModel):
    """Waiting time of the review queue."""

    length: int
    oldest_age_hours: float | None
    average_hours: float | None


class UploadDayResponse(BaseModel):
    """Materials uploaded on one day."""

    day: date
    count: int

    @classmethod
    def from_view(cls, view: UploadDayView) -> Self:
        """Map the read model."""
        return cls(day=view.day, count=view.count)


class SearchMissResponse(BaseModel):
    """A query that found nothing."""

    q: str
    count: int

    @classmethod
    def from_view(cls, view: SearchMissView) -> Self:
        """Map the read model."""
        return cls(q=view.q, count=view.count)


class TopItemResponse(BaseModel):
    """A much opened item."""

    item: ItemCardSchema
    opens: int

    @classmethod
    def from_view(cls, view: TopItemView) -> Self:
        """Map the read model."""
        return cls(item=ItemCardSchema.from_view(view.item), opens=view.opens)


class LibraryStatsResponse(BaseModel):
    """`LibraryStats`."""

    opens: int
    readers: int
    queue: QueueStatsResponse
    uploads_by_day: list[UploadDayResponse]
    searches_without_results: list[SearchMissResponse]
    top_items: list[TopItemResponse]
    items_by_status: dict[ItemStatus, int]
    reports_by_reason: dict[ReportReason, int]
    subjects_without_materials: list[SubjectRefSchema]

    @classmethod
    def from_view(cls, view: LibraryStatsView) -> Self:
        """Map the read model."""
        return cls(
            opens=view.opens,
            readers=view.readers,
            queue=QueueStatsResponse(
                length=view.queue.length,
                oldest_age_hours=view.queue.oldest_age_hours,
                average_hours=view.queue.average_hours,
            ),
            uploads_by_day=[
                UploadDayResponse.from_view(d) for d in view.uploads_by_day
            ],
            searches_without_results=[
                SearchMissResponse.from_view(m) for m in view.searches_without_results
            ],
            top_items=[TopItemResponse.from_view(t) for t in view.top_items],
            items_by_status=dict(view.items_by_status),
            reports_by_reason=dict(view.reports_by_reason),
            subjects_without_materials=[
                SubjectRefSchema(id=s.id, name=s.name)
                for s in view.subjects_without_materials
            ],
        )
