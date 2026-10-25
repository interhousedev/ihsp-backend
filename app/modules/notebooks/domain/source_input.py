"""What a student sends to add a source (`SourceInput` of § 4.4)."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class FileInput(BaseModel):
    """One of My files (PDF, DOCX, TXT, MD)."""

    kind: Literal["file"] = "file"
    file_id: UUID


class ChatInput(BaseModel):
    """An assistant chat up to a message (`until_seq`, default: the latest)."""

    kind: Literal["chat"] = "chat"
    chat_id: UUID
    until_seq: int | None = Field(default=None, ge=0)


class LessonResourceInput(BaseModel):
    """A material or attachment of a lesson the student attends."""

    kind: Literal["lesson_resource"] = "lesson_resource"
    lesson_id: UUID
    link_id: UUID


class FlashcardSetInput(BaseModel):
    """One of the student's flash card sets."""

    kind: Literal["flashcard_set"] = "flashcard_set"
    set_id: UUID


class LmsStepInput(BaseModel):
    """A step of an LMS course (text and flash card blocks only).

    A student adds the live step of a course they are enrolled in; a course workspace
    adds the *draft* of its own course's steps (`draft: true`).
    """

    kind: Literal["lms_step"] = "lms_step"
    course_id: UUID
    step_id: UUID
    draft: bool = False


class TextInput(BaseModel):
    """Pasted text."""

    kind: Literal["text"] = "text"
    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)


class NoteInput(BaseModel):
    """A note written by the student."""

    kind: Literal["note"] = "note"
    title: str = Field(min_length=1, max_length=255)
    body_md: str = Field(min_length=1)


class UrlInput(BaseModel):
    """A web page; Discover sends the title the search found for it."""

    kind: Literal["url"] = "url"
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=255)


class LibraryItemInput(BaseModel):
    """A library book or material, or a page range of one of its files.

    Without `file_id` the primary file is read. A whole textbook can be longer than
    a source may be, so a chapter range (`page_from`, `page_to`, 1-based and
    inclusive) keeps it under the limit.
    """

    kind: Literal["library_item"] = "library_item"
    item_id: UUID
    file_id: UUID | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _range_runs_forward(self) -> Self:
        """The first page of a range is not after its last page."""
        if (
            self.page_from is not None
            and self.page_to is not None
            and self.page_from > self.page_to
        ):
            raise ValueError("page_from must not be after page_to")
        return self


class LibraryNotesInput(BaseModel):
    """The student's own highlights and notes in a library book or material."""

    kind: Literal["library_notes"] = "library_notes"
    item_id: UUID


SourceInput = Annotated[
    FileInput
    | ChatInput
    | LessonResourceInput
    | FlashcardSetInput
    | LmsStepInput
    | TextInput
    | NoteInput
    | UrlInput
    | LibraryItemInput
    | LibraryNotesInput,
    Field(discriminator="kind"),
]
