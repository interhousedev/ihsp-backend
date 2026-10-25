"""Textbook plans and lesson links (doc § 7.1, LIB-11)."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from app.modules.library.application.reader.views import BookPlanView, NextSectionView
from app.modules.library.domain.book_plan import PlanSection
from app.modules.library.domain.reader_lesson_ref import LessonRefInput
from app.shared.contracts.library import LessonItemRefView

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class PlanSectionBody(BaseModel):
    """`{n, title, page_from, page_to, hours}`: one chapter of the plan."""

    model_config = ConfigDict(extra="forbid")

    n: int
    title: Annotated[str, StringConstraints(max_length=200)]
    page_from: int
    page_to: int
    hours: float = 1

    def to_section(self) -> PlanSection:
        """The domain section (the use case validates it)."""
        return PlanSection(
            n=self.n,
            title=self.title,
            page_from=self.page_from,
            page_to=self.page_to,
            hours=self.hours,
        )

    @classmethod
    def from_section(cls, section: PlanSection) -> Self:
        """Map a stored section."""
        return cls(
            n=section.n,
            title=section.title,
            page_from=section.page_from,
            page_to=section.page_to,
            hours=section.hours,
        )


class PutBookPlanBody(BaseModel):
    """`PUT /library/book-plans`: the textbook and its sections."""

    model_config = ConfigDict(extra="forbid")

    subject_id: UUID
    year_of_study: Annotated[int, Field(ge=1, le=4)]
    item_id: UUID
    sections: list[PlanSectionBody]


class BookPlanResponse(BaseModel):
    """`BookPlan`: the plan with the title of its book."""

    subject_id: UUID
    year_of_study: int
    item_id: UUID
    item_title: str
    sections: list[PlanSectionBody]
    updated_at: datetime

    @classmethod
    def from_view(cls, view: BookPlanView) -> Self:
        """Map the read model."""
        return cls(
            subject_id=view.subject_id,
            year_of_study=view.year_of_study,
            item_id=view.item_id,
            item_title=view.item_title,
            sections=[PlanSectionBody.from_section(s) for s in view.sections],
            updated_at=view.updated_at,
        )


class NextSectionResponse(BaseModel):
    """`{item_id, item_title, section}`: the suggested section."""

    item_id: UUID
    item_title: str
    section: PlanSectionBody

    @classmethod
    def from_view(cls, view: NextSectionView) -> Self:
        """Map the read model."""
        return cls(
            item_id=view.item_id,
            item_title=view.item_title,
            section=PlanSectionBody.from_section(view.section),
        )


class NextSuggestionResponse(BaseModel):
    """`{suggestion: ... | null}`."""

    suggestion: NextSectionResponse | None


class ItemRefTitle(BaseModel):
    """`{id, title}` of the linked book."""

    id: UUID
    title: str


class LessonItemRefResponse(BaseModel):
    """`LessonItemRef`: a section of a book that a lesson follows."""

    item: ItemRefTitle
    section_label: str
    page_from: int | None
    page_to: int | None

    @classmethod
    def from_view(cls, view: LessonItemRefView) -> Self:
        """Map the contract view."""
        return cls(
            item=ItemRefTitle(id=view.item_id, title=view.title),
            section_label=view.section_label,
            page_from=view.page_from,
            page_to=view.page_to,
        )


class LessonRefBody(BaseModel):
    """`{item_id, section_label, page_from, page_to}`."""

    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    section_label: str
    page_from: int | None = None
    page_to: int | None = None

    def to_input(self) -> LessonRefInput:
        """The input the use case validates."""
        return LessonRefInput(
            item_id=self.item_id,
            section_label=self.section_label,
            page_from=self.page_from,
            page_to=self.page_to,
        )


class SetLessonRefsBody(BaseModel):
    """`PUT /staff/lessons/{id}/item-refs`: `{refs: [...]}`."""

    model_config = ConfigDict(extra="forbid")

    refs: list[LessonRefBody]
