"""Use cases of the AI review block: a chat that reviews a student's work.

Trust boundary: the teacher prompt, reference files and private topics go to the
model but never to the student. Every answer is redacted before it is stored, so
neither the HTTP view nor the model history ever carries them. Student files and
messages are untrusted and reach the model only inside tags.

Modes: before any submission the reviewer only chats; ``submit`` spends one
submission and the model may ask one round of questions; the student's next message
(or a second submit) gets the final review in the teacher's template.
"""

import base64
import logging
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.next_card import require_enrolled
from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.source_reader import LmsSourceReaderImpl
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.step_context import (
    StepContext,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.authoring.errors import ContentInvalidError
from app.modules.lms.domain.learning import ai_review as review
from app.modules.lms.domain.learning.access import REVIEW
from app.modules.lms.domain.learning.ai_review_errors import (
    AiReviewClosedError,
    AiReviewFileRejectedError,
    AiReviewSessionNotFoundError,
    AiReviewUnavailableError,
)
from app.modules.lms.domain.learning.block_results import result_key, stored_result
from app.modules.lms.domain.learning.errors import (
    BlockNotFoundError,
    CourseNotFoundError,
)
from app.modules.lms.domain.step_content import AiReviewBlock
from app.modules.lms.ports.learning.ai_review_model import AiReviewModel, AiReviewWeb
from app.modules.lms.ports.learning.ai_review_store import (
    AiReviewMessageRecord,
    AiReviewSessionRecord,
    AiReviewStore,
    NewAiReviewMessage,
)
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.limits import LimitsProvider
from app.shared.rate_limit import RateLimiter
from app.shared.usage_context import bind_ai_session

from pydantic import BaseModel

log = logging.getLogger(__name__)

RATE_KEY = "lms:ai-review:{user_id}"
RATE_WINDOW_SECONDS = 60
DEFAULT_PER_MINUTE = 12
"""Turns per minute when the limits give none (staff): the limit is never off."""
MAX_IMAGE_BYTES = 5 * 1024 * 1024
STUDENT_PURPOSES = frozenset({FilePurpose.LMS_AI_REVIEW, FilePurpose.AI_UPLOAD})
UNUSABLE_STATUSES = frozenset({"deleted", "rejected"})


# - - - Views - - -


class AiReviewAttachmentView(BaseModel):
    """A file the student attached to a message."""

    file_id: UUID
    name: str
    content_type: str


class AiReviewMessageView(BaseModel):
    """One message; ``openui`` is a fenced, validated OpenUI block."""

    id: UUID
    role: Literal["student", "assistant"]
    text: str | None
    openui: str | None
    attachments: list[AiReviewAttachmentView]
    kind: Literal["chat", "question", "review"]
    created_at: datetime


class AiReviewSessionView(BaseModel):
    """A conversation with every message."""

    id: UUID
    step_id: UUID
    block_id: str
    status: Literal["open", "reviewed"]
    submissions_left: int
    messages: list[AiReviewMessageView]


class AiReviewSessionSummaryView(BaseModel):
    """A conversation in the student's list."""

    id: UUID
    status: Literal["open", "reviewed"]
    created_at: datetime
    submissions_used: int


class AiReviewMessagesView(BaseModel):
    """Messages a turn added (the student's and the reviewer's)."""

    messages: list[AiReviewMessageView]


class AiReviewStudentView(BaseModel):
    """Who submitted."""

    id: UUID
    name: str


class AiReviewSubmissionView(BaseModel):
    """A reviewed session as staff see it."""

    session_id: UUID
    student: AiReviewStudentView
    status: Literal["open", "reviewed"]
    submitted_at: datetime | None
    review_openui: str | None


def _message_view(m: AiReviewMessageRecord) -> AiReviewMessageView:
    assert m.created_at is not None
    return AiReviewMessageView(
        id=m.id,
        role=m.role,
        text=m.text,
        openui=m.openui,
        attachments=[AiReviewAttachmentView(**a) for a in m.attachments],
        kind=m.kind,
        created_at=m.created_at,
    )


@dataclass(frozen=True, slots=True)
class _Loaded:
    context: StepContext
    block: AiReviewBlock
    staff_refs: list[FileRef]


class AiReviews:
    """Sessions, messages and submissions of the AI review block."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        gate: AudienceGate,
        store: AiReviewStore,
        files: FilesApi,
        identity: IdentityDirectory,
        source_reader: LmsSourceReaderImpl,
        model: AiReviewModel | None,
        web: AiReviewWeb | None,
        limits: LimitsProvider,
        rate_limiter: RateLimiter,
        completion: StepCompletion,
    ) -> None:
        """Store collaborators; without a model the turns raise 503."""
        self.uow_factory = uow_factory
        self.gate = gate
        self.store = store
        self.files = files
        self.identity = identity
        self.source_reader = source_reader
        self.model = model
        self.web = web
        self.limits = limits
        self.rate_limiter = rate_limiter
        self.completion = completion

    def bind_model(self, model: AiReviewModel, web: AiReviewWeb | None) -> None:
        """Attach the model and web search once the ai module is built."""
        self.model = model
        self.web = web

    # - - - Access - - -

    async def _load(self, actor: Actor, step_id: UUID, block_id: str) -> _Loaded:
        """The enrolled student's live block and the reference files it may use.

        A reference file is used only when the block lists it, it was uploaded as
        an AI review file, it is usable and its owner is still staff of the course;
        `require_reference_access` checked the author could read it at save time.
        """
        async with self.uow_factory() as uow:
            context = await require_enrolled(uow, actor, step_id, self.gate)
            revision = await load_revision(uow, context.live_step.revision_id)
            block = next(
                (
                    b
                    for b in revision.content.blocks
                    if isinstance(b, AiReviewBlock) and b.id == block_id
                ),
                None,
            )
            if block is None:
                raise BlockNotFoundError(params={"block_id": block_id})
            refs = await self.files.get_many(
                [i for i in (_uuid(f.file_id) for f in block.reference_files) if i]
            )
            staff_refs = [
                ref
                for ref in refs.values()
                if ref.purpose == FilePurpose.LMS_AI_REVIEW
                and ref.status not in UNUSABLE_STATUSES
                and await uow.staff.get(context.course.id, ref.owner_id) is not None
            ]
        return _Loaded(context=context, block=block, staff_refs=staff_refs)

    async def _own_session(
        self, actor: Actor, session_id: UUID
    ) -> tuple[AiReviewSessionRecord, _Loaded]:
        session = await self.store.get_session(session_id)
        if session is None or session.user_id != actor.user_id:
            raise AiReviewSessionNotFoundError(params={"session_id": str(session_id)})
        return session, await self._load(actor, session.step_id, session.block_id)

    async def _used(self, actor: Actor, step_id: UUID, block_id: str) -> int:
        """Submissions of the student for the block across all their sessions."""
        sessions = await self.store.list_sessions(
            step_id=step_id, block_id=block_id, user_id=actor.user_id
        )
        return sum(s.submissions_used for s in sessions)

    async def _session_view(
        self, actor: Actor, session: AiReviewSessionRecord, block: AiReviewBlock
    ) -> AiReviewSessionView:
        used = await self._used(actor, session.step_id, session.block_id)
        messages = await self.store.messages(session.id)
        return AiReviewSessionView(
            id=session.id,
            step_id=session.step_id,
            block_id=session.block_id,
            status=session.status,
            submissions_left=max(block.max_submissions - used, 0),
            messages=[_message_view(m) for m in messages],
        )

    # - - - Use cases - - -

    async def create_session(
        self, actor: Actor, step_id: UUID, block_id: str
    ) -> AiReviewSessionView:
        """Open a new conversation about the block."""
        loaded = await self._load(actor, step_id, block_id)
        session = await self.store.create_session(
            course_id=loaded.context.course.id,
            step_id=step_id,
            block_id=block_id,
            user_id=actor.user_id,
        )
        return await self._session_view(actor, session, loaded.block)

    async def list_sessions(
        self, actor: Actor, step_id: UUID, block_id: str
    ) -> list[AiReviewSessionSummaryView]:
        """The student's own conversations about the block, newest first."""
        await self._load(actor, step_id, block_id)
        sessions = await self.store.list_sessions(
            step_id=step_id, block_id=block_id, user_id=actor.user_id
        )
        return [
            AiReviewSessionSummaryView(
                id=s.id,
                status=s.status,
                created_at=s.created_at,
                submissions_used=s.submissions_used,
            )
            for s in sessions
        ]

    async def get_session(self, actor: Actor, session_id: UUID) -> AiReviewSessionView:
        """One of the student's own conversations."""
        session, loaded = await self._own_session(actor, session_id)
        return await self._session_view(actor, session, loaded.block)

    async def send_message(
        self, actor: Actor, session_id: UUID, text: str, file_ids: Sequence[UUID]
    ) -> AiReviewMessagesView:
        """A chat turn; after a question round it brings the final review."""
        session, loaded = await self._own_session(actor, session_id)
        if session.status == "reviewed":
            raise AiReviewClosedError(params={"session_id": str(session_id)})
        history = await self.store.messages(session_id)
        asked = bool(history) and history[-1].kind == "question"
        mode: review.Mode = "final" if asked else "chat"
        return await self._turn(
            actor, session, loaded, history, text, file_ids, mode, submission=False
        )

    async def submit(
        self, actor: Actor, session_id: UUID, file_ids: Sequence[UUID], note: str
    ) -> AiReviewMessagesView:
        """Spend one submission; the reviewer may ask once, then reviews."""
        session, loaded = await self._own_session(actor, session_id)
        if session.status == "reviewed":
            raise AiReviewClosedError(params={"session_id": str(session_id)})
        history = await self.store.messages(session_id)
        asked = bool(history) and history[-1].kind == "question"
        mode: review.Mode = "final" if asked else "may_ask"
        return await self._turn(
            actor, session, loaded, history, note, file_ids, mode, submission=True
        )

    async def list_submissions(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> list[AiReviewSubmissionView]:
        """Staff: every session of the block with at least one submission."""
        async with self.uow_factory() as uow:
            access = await staff_access(uow, actor, course_id)
            if not access.can(REVIEW):
                raise ForbiddenError()
            step = await uow.steps.get(step_id)
            if step is None or step.course_id != course_id:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
        sessions = [
            s
            for s in await self.store.list_sessions(step_id=step_id, block_id=block_id)
            if s.submissions_used > 0
        ]
        users = await self.identity.get_users([s.user_id for s in sessions])
        out = []
        for s in sessions:
            reviews = [m for m in await self.store.messages(s.id) if m.kind == "review"]
            last = reviews[-1] if reviews else None
            user = users.get(s.user_id)
            name = f"{user.last_name} {user.first_name}".strip() if user else ""
            out.append(
                AiReviewSubmissionView(
                    session_id=s.id,
                    student=AiReviewStudentView(id=s.user_id, name=name),
                    status=s.status,
                    submitted_at=last.created_at if last else s.updated_at,
                    review_openui=last.openui if last else None,
                )
            )
        return out

    # - - - The model turn - - -

    async def _turn(
        self,
        actor: Actor,
        session: AiReviewSessionRecord,
        loaded: _Loaded,
        history: Sequence[AiReviewMessageRecord],
        text: str,
        file_ids: Sequence[UUID],
        mode: review.Mode,
        *,
        submission: bool,
    ) -> AiReviewMessagesView:
        if self.model is None:
            raise AiReviewUnavailableError()
        limits = await self.limits.for_actor(actor)
        await self.rate_limiter.hit(
            RATE_KEY.format(user_id=actor.user_id),
            limit=limits.lms_ai_chat_per_minute or DEFAULT_PER_MINUTE,
            window_seconds=RATE_WINDOW_SECONDS,
        )
        block = loaded.block
        text = text[: review.MAX_TEXT_CHARS]
        refs = await self._student_files(actor, block, file_ids)
        if mode != "chat" and not refs:
            refs = await self._student_files(actor, block, _last_files(history))
        if submission:
            await self.store.reserve_submission(
                session.id, max_submissions=block.max_submissions
            )
        try:
            return await self._answer(actor, session, loaded, history, text, refs, mode)
        except BaseException:
            if submission:
                await self.store.refund_submission(session.id)
            raise

    async def _answer(
        self,
        actor: Actor,
        session: AiReviewSessionRecord,
        loaded: _Loaded,
        history: Sequence[AiReviewMessageRecord],
        text: str,
        refs: Sequence[FileRef],
        mode: review.Mode,
    ) -> AiReviewMessagesView:
        """Call the model, filter its answer, store the turn (submission reserved)."""
        assert self.model is not None
        block = loaded.block
        work = [await self._work_file(ref) for ref in refs]
        locale = (await self.identity.get_preferences(actor.user_id)).locale
        reference_text = await self._reference_text(loaded.staff_refs)
        canary = review.new_canary()
        context = review.ReviewContext(
            block=block,
            locale=locale,
            work=work,
            reference_text=reference_text,
            materials=await self._materials(actor, loaded),
            web=await self._web(actor, block, text, locale, mode),
            canary=canary,
        )
        messages: list[dict[str, object]] = [
            {
                "role": "user" if m.role == "student" else "assistant",
                "content": m.history or "-",
            }
            for m in history[-review.MAX_HISTORY :]
        ]
        messages.append({"role": "user", "content": review.work_content(text, work)})
        bind_ai_session("lms_ai_review", session.id)
        answer = await self.model.answer(
            system=review.system_prompt(context, mode), messages=messages
        )
        answer = review.forced(answer, mode)
        passed = answer.kind == "review" and review.review_passed(answer, block)
        answer = review.redact_answer(
            answer, review.secrets_of(block, reference_text, canary)
        )
        source = review.openui_of(
            answer, block, locale, [w.name for w in work if w.image_data_url]
        )
        openui = await self.model.finalize(source) if source else None
        student_history = review.tagged("student_message", text or "-") + (
            "\nFiles: " + ", ".join(r.name for r in refs) if refs else ""
        )
        new = [
            NewAiReviewMessage(
                role="student",
                kind="chat",
                text=text or None,
                openui=None,
                history=student_history,
                attachments=[
                    {
                        "file_id": str(r.id),
                        "name": r.name,
                        "content_type": r.content_type,
                    }
                    for r in refs
                ],
            ),
            NewAiReviewMessage(
                role="assistant",
                kind=answer.kind,
                text=answer.message or None,
                openui=openui,
                history=review.plain_text(answer),
            ),
        ]
        stored = await self.store.append(
            session.id,
            new,
            status="reviewed" if answer.kind == "review" else None,
        )
        if answer.kind == "review":
            await self._mark_reviewed(actor, session.step_id, session.block_id, passed)
        return AiReviewMessagesView(messages=[_message_view(m) for m in stored])

    async def _mark_reviewed(
        self, actor: Actor, step_id: UUID, block_id: str, passed: bool
    ) -> None:
        """Record the review in the step state; only a pass completes the block.

        `passed` comes from the server-clamped scores against the author's
        threshold, never from the model's word; a pass once given is kept.
        """
        now = datetime.now(UTC)
        async with self.uow_factory() as uow:
            cards = (await uow.states.cards_by_step(actor.user_id, [step_id])).get(
                step_id, {}
            )
            before = stored_result(cards, block_id) or {}
            done = bool(before.get("passed")) or passed
            await uow.states.save_card(
                actor.user_id,
                step_id,
                result_key(block_id),
                {"kind": "ai_review", "passed": done, "completed": done},
                now=now,
            )
            await self.completion.after_block_result(uow, actor.user_id, step_id, now)
            await uow.commit()

    async def _student_files(
        self, actor: Actor, block: AiReviewBlock, file_ids: Sequence[UUID]
    ) -> list[FileRef]:
        """The student's own uploads of an accepted type, at most five."""
        if len(file_ids) > review.MAX_FILES_PER_MESSAGE:
            raise AiReviewFileRejectedError(
                params={"max": review.MAX_FILES_PER_MESSAGE}
            )
        found = await self.files.get_many(list(dict.fromkeys(file_ids)))
        accepted = review.accepted_content_types(block)
        refs = []
        for file_id in dict.fromkeys(file_ids):
            ref = found.get(file_id)
            if (
                ref is None
                or ref.owner_id != actor.user_id
                or ref.purpose not in STUDENT_PURPOSES
                or ref.content_type not in accepted
            ):
                raise AiReviewFileRejectedError(params={"file_id": str(file_id)})
            refs.append(ref)
        return refs

    async def _work_file(self, ref: FileRef) -> review.WorkFile:
        if ref.content_type in review.IMAGE_TYPES:
            if ref.byte_size > MAX_IMAGE_BYTES:
                return review.WorkFile(name=ref.name, content_type=ref.content_type)
            data = base64.b64encode(await self.files.read_bytes(ref.id)).decode()
            return review.WorkFile(
                name=ref.name,
                content_type=ref.content_type,
                image_data_url=f"data:{ref.content_type};base64,{data}",
            )
        return review.WorkFile(
            name=ref.name, content_type=ref.content_type, text=await self._text(ref)
        )

    async def _text(self, ref: FileRef) -> str:
        try:
            return (await self.files.read_text_with_pages(ref.id)).text
        except Exception:  # noqa: BLE001 - a file without text is reviewed by name
            log.info("lms ai review: no text for file %s", ref.id)
            return ""

    async def _reference_text(self, refs: Sequence[FileRef]) -> str:
        parts = [f"## {r.name}\n{await self._text(r)}" for r in refs]
        return "\n\n".join(parts)[: review.MAX_REFERENCE_CHARS]

    async def _materials(self, actor: Actor, loaded: _Loaded) -> str:
        if not loaded.block.use_course_materials:
            return ""
        step = await self.source_reader.step_text(
            actor.user_id, loaded.context.course.id, loaded.context.step.id
        )
        return f"# {step.title}\n{step.text}"[: review.MAX_MATERIAL_CHARS]

    async def _web(
        self,
        actor: Actor,
        block: AiReviewBlock,
        text: str,
        locale: str,
        mode: review.Mode,
    ) -> str:
        if not block.web_search or self.web is None or mode == "chat":
            return ""
        query = f"{block.title} {text}".strip()
        return (await self.web.search(actor, query=query, locale=locale))[
            : review.MAX_WEB_CHARS
        ]


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _last_files(history: Sequence[AiReviewMessageRecord]) -> list[UUID]:
    """The files of the latest student message that had any."""
    for m in reversed(history):
        if m.role == "student" and m.attachments:
            return [UUID(a["file_id"]) for a in m.attachments]
    return []


async def require_reference_access(
    files: FilesApi, actor: Actor | None, content: Mapping[str, Any], known: Set[UUID]
) -> None:
    """Refuse AI review reference files the saving author may not read.

    Every newly listed reference file (not in `known`, the ones already in the
    draft) must exist, be an AI review upload and be readable by the author;
    content saved without an author may not add any. Raises ContentInvalidError
    with reason ``ai-review-file``.
    """
    wanted = [i for i in reference_file_ids(content) if i not in known]
    if not wanted:
        return
    found = await files.get_many(wanted)
    wrong = [
        str(i)
        for i in wanted
        if i not in found
        or found[i].purpose != FilePurpose.LMS_AI_REVIEW
        or found[i].status in UNUSABLE_STATUSES
        or actor is None
        or not await files.check_access(i, actor)
    ]
    if wrong:
        raise ContentInvalidError(
            params={"reason": "ai-review-file", "file_ids": wrong}
        )


def reference_file_ids(content: Mapping[str, Any]) -> list[UUID]:
    """The reference file ids of every AI review block of step content (JSON)."""
    ids: list[UUID] = []
    for block in content.get("blocks") or []:
        if block.get("type") != "ai_review":
            continue
        for item in block.get("reference_files") or []:
            file_id = _uuid(str(item.get("file_id", "")))
            if file_id is not None and file_id not in ids:
                ids.append(file_id)
    return ids
