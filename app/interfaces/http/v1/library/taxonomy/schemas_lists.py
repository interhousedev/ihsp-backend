"""Reading lists of the TypeScript contract (web `library.ts`: `ReadingList*`)."""

from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import (
    ItemCardSchema,
    SubjectRefSchema,
)
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import sent
from app.modules.library.application.taxonomy.update_reading_list import ListChanges
from app.modules.library.application.taxonomy.views import (
    PersonView,
    ReadingListCardView,
    ReadingListDetailView,
    ReadingListEntryView,
)
from app.modules.library.domain.enums import (
    Importance,
    ListScope,
    ListStatus,
    ShelfState,
)
from app.modules.library.domain.reading_list import EntryDraft
from app.modules.library.domain.taxonomy_unset import UNSET

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class PersonResponse(BaseModel):
    """`{id, name}` of the owner of a list."""

    id: UUID
    name: str

    @classmethod
    def from_view(cls, view: PersonView) -> Self:
        """Map the read model."""
        return cls(id=view.id, name=view.name)


class ReadingListCardResponse(BaseModel):
    """`ReadingListCard`."""

    id: UUID
    title: str
    description: str | None
    scope: ListScope
    status: ListStatus
    subject: SubjectRefSchema | None
    year_of_study: int | None
    academic_year: str | None
    term_half: Literal[1, 2] | None
    owner: PersonResponse
    entry_count: int
    essential_count: int
    essential_done: int
    updated_at: datetime

    @classmethod
    def from_view(cls, view: ReadingListCardView) -> Self:
        """Map the read model."""
        return cls(
            id=view.id,
            title=view.title,
            description=view.description,
            scope=view.scope,
            status=view.status,
            subject=(
                SubjectRefSchema(id=view.subject.id, name=view.subject.name)
                if view.subject
                else None
            ),
            year_of_study=view.year_of_study,
            academic_year=view.academic_year,
            term_half=1 if view.term_half == 1 else 2 if view.term_half == 2 else None,
            owner=PersonResponse.from_view(view.owner),
            entry_count=view.entry_count,
            essential_count=view.essential_count,
            essential_done=view.essential_done,
            updated_at=view.updated_at,
        )


class ReadingListEntryResponse(BaseModel):
    """`ReadingListEntry`: an item card or a plain link, with my read status."""

    position: int
    item: ItemCardSchema | None
    url: str | None
    title: str | None
    importance: Importance
    page_from: int | None
    page_to: int | None
    week_label: str | None
    due_on: date | None
    topic_id: UUID | None
    note: str | None
    read_state: ShelfState | None

    @classmethod
    def from_view(cls, view: ReadingListEntryView) -> Self:
        """Map the read model."""
        return cls(
            position=view.position,
            item=ItemCardSchema.from_view(view.item) if view.item else None,
            url=view.url,
            title=view.title,
            importance=view.importance,
            page_from=view.page_from,
            page_to=view.page_to,
            week_label=view.week_label,
            due_on=view.due_on,
            topic_id=view.topic_id,
            note=view.note,
            read_state=view.read_state,
        )


class ReadingListDetailResponse(ReadingListCardResponse):
    """`ReadingListDetail`: the card, the groups, the entries, `can_edit`."""

    group_ids: list[UUID]
    entries: list[ReadingListEntryResponse]
    can_edit: bool

    @classmethod
    def from_detail(cls, view: ReadingListDetailView) -> Self:
        """Map the read model."""
        card = ReadingListCardResponse.from_view(view.card)
        return cls(
            **card.model_dump(),
            group_ids=list(view.group_ids),
            entries=[ReadingListEntryResponse.from_view(e) for e in view.entries],
            can_edit=view.can_edit,
        )


TermHalf = Literal[1, 2]
ListTitle = Annotated[str, StringConstraints(max_length=300)]


class CreateReadingListBody(BaseModel):
    """`ReadingListInput`."""

    model_config = ConfigDict(extra="forbid")

    title: ListTitle
    scope: ListScope
    description: str | None = None
    subject_id: UUID | None = None
    group_ids: list[UUID] = Field(default_factory=list)
    year_of_study: int | None = None
    academic_year: str | None = None
    term_half: TermHalf | None = None
    status: ListStatus = ListStatus.DRAFT


class UpdateReadingListBody(BaseModel):
    """`Partial<ReadingListInput>`: only the keys that were sent are applied."""

    model_config = ConfigDict(extra="forbid")

    title: ListTitle | None = None
    scope: ListScope | None = None
    description: str | None = None
    subject_id: UUID | None = None
    group_ids: list[UUID] | None = None
    year_of_study: int | None = None
    academic_year: str | None = None
    term_half: TermHalf | None = None
    status: ListStatus | None = None

    def to_changes(self) -> ListChanges:
        """What the use case applies; fields not sent stay as they are."""
        return ListChanges(
            title=self.title if self.title is not None else UNSET,
            description=sent(self, "description", self.description),
            scope=self.scope if self.scope is not None else UNSET,
            subject_id=sent(self, "subject_id", self.subject_id),
            group_ids=self.group_ids if self.group_ids is not None else UNSET,
            year_of_study=sent(self, "year_of_study", self.year_of_study),
            academic_year=sent(self, "academic_year", self.academic_year),
            term_half=sent(self, "term_half", self.term_half),
            status=self.status if self.status is not None else UNSET,
        )


class ReadingListItemBody(BaseModel):
    """`ReadingListItemInput`."""

    model_config = ConfigDict(extra="forbid")

    importance: Importance
    item_id: UUID | None = None
    url: str | None = None
    title: str | None = None
    page_from: int | None = None
    page_to: int | None = None
    week_label: str | None = None
    due_on: date | None = None
    topic_id: UUID | None = None
    note: str | None = None

    def to_draft(self) -> EntryDraft:
        """The entry as the use case checks it."""
        return EntryDraft(
            importance=self.importance,
            item_id=self.item_id,
            url=self.url,
            title=self.title,
            page_from=self.page_from,
            page_to=self.page_to,
            week_label=self.week_label,
            due_on=self.due_on,
            topic_id=self.topic_id,
            note=self.note,
        )


class ReplaceEntriesBody(BaseModel):
    """`PUT /library/reading-lists/{id}/items`: `{items: ReadingListItemInput[]}`."""

    model_config = ConfigDict(extra="forbid")

    items: list[ReadingListItemBody]
