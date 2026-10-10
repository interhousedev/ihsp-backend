"""Entities and jsonb payload models of the notebooks module (§ 4.1)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    ChatLanguage,
    ChatLength,
    ChatStyle,
    GuideStatus,
    MessageRole,
    NotebookOrigin,
    SourceFailure,
    SourceKind,
    SourceStatus,
    SummaryStatus,
)
from app.shared.contracts.web_search import WebResult

from pydantic import BaseModel, Field

# - - - jsonb payloads (validated on read and write) - - -


class ChatConfig(BaseModel):
    """`notebooks.chat_config` (§ 3.3.6)."""

    style: ChatStyle = ChatStyle.DEFAULT
    custom_prompt: str | None = Field(default=None, max_length=1000)
    length: ChatLength = ChatLength.DEFAULT
    language: ChatLanguage = ChatLanguage.AUTO
    goal: str | None = Field(default=None, max_length=300)


class ExcludedRef(BaseModel):
    """A material the student left out of an auto notebook (kept across re-syncs)."""

    ref_key: str = Field(max_length=300)
    title: str = Field(default="", max_length=255)


class AutoSettings(BaseModel):
    """`notebooks.auto_settings`: what an auto notebook syncs (subject and lesson)."""

    include_classmates: bool = False
    excluded_refs: list[ExcludedRef] = Field(default_factory=list, max_length=500)

    @property
    def excluded_keys(self) -> frozenset[str]:
        """The duplicate keys (`lesson:<link_id>`) the sync must skip."""
        return frozenset(item.ref_key for item in self.excluded_refs)


class NotebookSummary(BaseModel):
    """`notebooks.summary` (§ 3.2.6)."""

    summary: str
    key_topics: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    generated_at: datetime


class SourceGuide(BaseModel):
    """`sources.guide` (§ 3.2.5)."""

    summary: str
    key_topics: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    """A numbered citation with a snapshot of the cited passage (§ 3.3.5)."""

    n: int
    passage_id: UUID
    source_id: UUID
    source_title: str
    source_kind: SourceKind
    page: int | None = None
    snippet: str


class AnchorPassages(BaseModel):
    """Pins passages (flash card or quiz Explain, "Ask about this", mind map node)."""

    kind: Literal["passages"] = "passages"
    ids: list[UUID] = Field(default_factory=list, max_length=20)


class AnchorText(BaseModel):
    """Pins a piece of text the student selected."""

    kind: Literal["text"] = "text"
    text: str = Field(max_length=4000)


Anchor = Annotated[AnchorPassages | AnchorText, Field(discriminator="kind")]


class MessageContent(BaseModel):
    """`messages.content` (§ 3.3.5)."""

    text: str = ""
    citations: list[Citation] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)  # S1.. = list order
    retrieval: bool = False
    grounded: bool = False
    anchor: AnchorPassages | AnchorText | None = Field(
        default=None, discriminator="kind"
    )
    web: list[WebResult] = Field(default_factory=list)  # pages of the web search


class ArtifactError(BaseModel):
    """`artifacts.error`."""

    code: str
    message_key: str
    params: dict[str, Any] = Field(default_factory=dict)


# - - - entities - - -


@dataclass(slots=True)
class Notebook:
    """A student's private collection of sources."""

    id: UUID
    owner_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    title_auto: bool = True
    emoji: str | None = None
    emoji_auto: bool = True
    pinned: bool = False
    chat_config: ChatConfig = field(default_factory=ChatConfig)
    summary: NotebookSummary | None = None
    summary_status: SummaryStatus = SummaryStatus.NONE
    summary_due_at: datetime | None = None
    summary_hash: str | None = None
    source_count: int = 0
    char_count: int = 0
    last_opened_at: datetime | None = None
    deleted_at: datetime | None = None
    # Auto notebooks (subject / lesson): the system keeps their lesson sources in step
    # with the lesson materials; `auto_settings` is set exactly for those.
    origin: NotebookOrigin = NotebookOrigin.MANUAL
    subject_id: UUID | None = None
    lesson_id: UUID | None = None
    auto_settings: AutoSettings | None = None
    auto_synced_at: datetime | None = None
    space_key: str | None = None  # the shared course space the notebook belongs to
    # Course workspace (`origin` is `course`): the LMS course whose staff share it.
    # Student course notebook (`course_student`): the course the student is enrolled in.
    course_id: UUID | None = None
    # Not stored: counted by the repository when the notebook is read.
    ready_source_count: int = 0
    selected_source_count: int = 0
    # Not stored: set by the access check; False for a read-only member of the course.
    can_write: bool = True

    @property
    def is_deleted(self) -> bool:
        """True after the owner deleted it (kept 7 days)."""
        return self.deleted_at is not None

    @property
    def is_auto(self) -> bool:
        """True for a subject or lesson notebook the system maintains."""
        return self.origin.is_auto

    @property
    def is_course_workspace(self) -> bool:
        """True for the workspace of an LMS course (shared by the course staff)."""
        return self.origin is NotebookOrigin.COURSE

    @property
    def is_course_student(self) -> bool:
        """True for the student's own notebook of an LMS course they are enrolled in."""
        return self.origin is NotebookOrigin.COURSE_STUDENT


@dataclass(slots=True)
class Source:
    """One text the notebook is grounded in."""

    id: UUID
    notebook_id: UUID
    owner_id: UUID
    kind: SourceKind
    title: str
    position: int
    created_at: datetime
    updated_at: datetime
    ref: dict[str, Any] = field(default_factory=dict)
    ref_key: str | None = None
    origin: dict[str, Any] | None = None
    selected: bool = True
    status: SourceStatus = SourceStatus.PENDING
    failure: SourceFailure | None = None
    body_md: str | None = None
    citations: list[Citation] | None = None
    content_hash: str | None = None
    document_id: UUID | None = None  # the shared text; passages belong to it
    upstream_version: str | None = None
    word_count: int = 0
    char_count: int = 0
    token_estimate: int = 0
    passage_count: int = 0
    guide: SourceGuide | None = None
    guide_status: GuideStatus = GuideStatus.NONE
    text_synced_at: datetime | None = None
    # Not stored here: the topic labels on the source (read with the source).
    label_ids: list[UUID] = field(default_factory=list)

    @property
    def editable(self) -> bool:
        """Pasted text and notes without citations can be edited."""
        return self.kind in (SourceKind.TEXT, SourceKind.NOTE) and not self.citations

    @property
    def usable(self) -> bool:
        """Ready and stale sources feed the chat and Studio."""
        return self.status.usable


@dataclass(frozen=True, slots=True)
class Document:
    """One distinct normalized text, shared by every source that holds it."""

    id: UUID
    content_hash: str
    word_count: int
    char_count: int
    token_estimate: int
    passage_count: int


@dataclass(frozen=True, slots=True)
class CachedSummary:
    """A notebook summary kept for a set of texts (title and emoji as proposed)."""

    title: str
    emoji: str | None
    summary: NotebookSummary


@dataclass(frozen=True, slots=True)
class CachedArtifact:
    """A finished Studio output kept for everyone who asks for the same thing."""

    cache_key: str
    kind: ArtifactKind
    title: str
    format: str | None
    content: dict[str, Any]
    refs_index: dict[str, Any] | None
    source_map: dict[str, str]
    source_documents: dict[str, str]  # source id -> document id of the generator
    options: dict[str, Any]
    sampled: bool
    model: str | None


@dataclass(frozen=True, slots=True)
class DraftPassage:
    """A passage produced by the chunker, before it has an id (§ 3.2.3)."""

    seq: int
    text: str
    char_start: int
    char_end: int
    token_estimate: int
    page: int | None = None
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class Passage:
    """A stored passage: the unit of citation, retrieval and the source viewer."""

    id: UUID
    source_id: UUID
    notebook_id: UUID
    seq: int
    text: str
    char_start: int
    char_end: int
    token_estimate: int
    page: int | None = None
    heading: str | None = None
    content_hash: str = ""  # `passage_hash(text)`; filled by the SQL repository


@dataclass(slots=True)
class NotebookMessage:
    """One message of the notebook chat (one thread per notebook and user)."""

    id: UUID
    notebook_id: UUID
    user_id: UUID
    seq: int
    role: MessageRole
    content: MessageContent
    created_at: datetime
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    weighted: int | None = None
    model: str | None = None
    feedback: int | None = None  # 1 up, -1 down
    stopped: bool = False


@dataclass(slots=True)
class Artifact:
    """A Studio output (§ 3.4)."""

    id: UUID
    notebook_id: UUID
    owner_id: UUID
    kind: ArtifactKind
    title: str
    created_at: datetime
    updated_at: datetime
    status: ArtifactStatus = ArtifactStatus.QUEUED
    format: str | None = None
    error: ArtifactError | None = None
    options: dict[str, Any] = field(default_factory=dict)
    prompt: str | None = None
    source_ids: list[UUID] = field(default_factory=list)
    source_map: dict[str, str] = field(default_factory=dict)
    sampled: bool = False
    content: dict[str, Any] | None = None
    refs_index: dict[str, Any] | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    weighted: int | None = None
    cost_micro: int | None = None
    attempts: int = 0
    progress: int | None = None
    parent_id: UUID | None = None
    flashcard_set_id: UUID | None = None
    cache_key: str | None = (
        None  # shared Studio cache entry (stored under or served from)
    )
    from_cache: bool = False  # served from the shared cache: no model call was made
    started_at: datetime | None = None
    finished_at: datetime | None = None
    viewed_at: datetime | None = None
    deleted_at: datetime | None = None
    # Who asked for it in a shared notebook (a course workspace); None means the owner.
    requested_by: UUID | None = None

    @property
    def charged_to(self) -> UUID:
        """The user whose budget, quota and bell the output uses."""
        return self.requested_by or self.owner_id

    @property
    def unread(self) -> bool:
        """A finished output the student has not opened yet (the blue dot)."""
        return self.status is ArtifactStatus.READY and self.viewed_at is None


@dataclass(slots=True)
class ArtifactProgress:
    """A student's progress in a flash card deck or quiz (resume where they left)."""

    artifact_id: UUID
    user_id: UUID
    state: dict[str, Any]
    updated_at: datetime
