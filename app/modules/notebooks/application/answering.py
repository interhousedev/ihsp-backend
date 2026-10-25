"""One grounded answer (§ 3.3.1): asking, regenerating and streaming share this code.

`AnswerPipeline` holds the turn lock for the whole answer, reads the context in one
short transaction, calls the model while no transaction is open, then stores the
messages in one more. Nothing here logs prompts, sources or answers (ids and sizes
only, § 3.7).
"""

import asyncio
import re
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from typing import Any, Final, cast
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.history_compactor import (
    history_limit,
    window_only,
)
from app.modules.notebooks.application.llm import StreamItem
from app.modules.notebooks.application.views import (
    NotebookUsageView,
    QuotaView,
    StreamEvent,
    TurnView,
    UsagePartView,
)
from app.modules.notebooks.domain.chat_action import split_action
from app.modules.notebooks.domain.citations import (
    CitationPiece,
    DeltaPiece,
    ProcessedAnswer,
    StreamingAnswer,
    StreamPiece,
    process_answer,
)
from app.modules.notebooks.domain.compaction import COMPACT_LOOKBACK, summary_note
from app.modules.notebooks.domain.context import ContextPack, CourseContext
from app.modules.notebooks.domain.entities import (
    AnchorPassages,
    AnchorText,
    ChatConfig,
    Citation,
    MessageContent,
    NotebookMessage,
    Source,
)
from app.modules.notebooks.domain.enums import ChatLength, MessageRole
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NoSourcesSelectedError,
    NotebookNotFoundError,
)
from app.modules.notebooks.domain.history import history_messages
from app.modules.notebooks.domain.language import resolve_language
from app.modules.notebooks.domain.limits import CHAT_MESSAGE_MAX_CHARS
from app.modules.notebooks.domain.modality import readable_by
from app.modules.notebooks.domain.prompts.chat import (
    chat_system_prompt,
    question_message,
)
from app.modules.notebooks.domain.prompts.web import WEB_INTRO
from app.modules.notebooks.domain.sources_block import anchor_note, render_sources_block
from app.modules.notebooks.domain.tokens import Usage, estimate_cost, estimate_tokens
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor, Role
from app.shared.agent_steps import (
    AgentStep,
    StepKind,
    StepRecorder,
    current_steps,
    recording,
    step,
)
from app.shared.ai_tasks import AiTask
from app.shared.base_error import BaseError
from app.shared.clock import local_today
from app.shared.contracts.web_search import WebResult, WebSearchDisabledError
from app.shared.ids import new_id
from app.shared.openui.prompt import openui_prompt
from app.shared.web_citations import (
    WebMarkers,
    cited_in,
    numbered,
    render_web_block,
    rewrite_markers,
)

import structlog

log = structlog.get_logger(__name__)

MAX_TOKENS: Final = {
    ChatLength.SHORTER: 400,
    ChatLength.DEFAULT: 1000,
    ChatLength.LONGER: 2000,
}
RATE_WINDOW_SECONDS: Final = 60
WEB_RESERVE_CHARS: Final = 8000  # the budget check allows for the web results
FEEDBACK_NAMES: Final = {1: "up", -1: "down"}
_CHIP = re.compile(r"⟦([\d,]+)⟧")


NO_SOURCES_NOTE = (
    "No sources are selected. Answer from general knowledge, say briefly that the "
    "answer is not based on the notebook's materials, and do not cite sources."
)


def clean_question(text: str) -> str:
    """Return the trimmed question; it must have 1 to 4 000 characters.

    Raises:
        InvalidOptionsError: The question is empty or too long.
    """
    clean = text.strip()
    if not clean or len(clean) > CHAT_MESSAGE_MAX_CHARS:
        raise InvalidOptionsError(
            params={"reason": "text-length", "max": CHAT_MESSAGE_MAX_CHARS}
        )
    return clean


def message_payload(message: NotebookMessage) -> dict[str, Any]:
    """The JSON-ready ``NotebookMessage`` of § 4.4 (used by the ``done`` event)."""
    content = message.content
    return {
        "id": str(message.id),
        "seq": message.seq,
        "role": message.role.value,
        "text": content.text,
        "citations": [item.model_dump(mode="json") for item in content.citations],
        "followups": list(content.followups),
        "source_ids": [str(source_id) for source_id in content.source_ids],
        "web": [item.model_dump(mode="json") for item in content.web],
        "steps": [item.model_dump(mode="json") for item in content.steps],
        "retrieval": content.retrieval,
        "grounded": content.grounded,
        "feedback": (
            FEEDBACK_NAMES.get(message.feedback, None)
            if message.feedback is not None
            else None
        ),
        "stopped": message.stopped,
        "created_at": message.created_at.isoformat(),
    }


def _part_payload(part: UsagePartView | QuotaView) -> dict[str, Any]:
    reset = part.resets_at
    return {
        "used": part.used,
        "limit": part.limit,
        "resets_at": reset.isoformat() if reset is not None else None,
    }


def usage_payload(view: NotebookUsageView) -> dict[str, Any]:
    """The JSON-ready ``NotebookUsage`` of § 4.4."""
    return {
        "budget": {
            "session": _part_payload(view.session),
            "day": _part_payload(view.day),
        },
        "quotas": {name: _part_payload(quota) for name, quota in view.quotas.items()},
        "generating": view.generating,
        "generating_limit": view.generating_limit,
    }


async def load_own_answer(
    uow: NotebooksUnitOfWork, user_id: UUID, notebook_id: UUID, message_id: UUID
) -> NotebookMessage:
    """Return an assistant message of the user's own thread, else a 404."""
    await load_notebook(uow, user_id, notebook_id, write=False)
    message = await uow.messages.get(message_id)
    if (
        message is None
        or message.notebook_id != notebook_id
        or message.user_id != user_id
        or message.role is not MessageRole.ASSISTANT
    ):
        raise NotebookNotFoundError()
    return message


# - - - values passed between the steps - - -


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    """A question to answer; ``text=None`` answers the last question again."""

    user_id: UUID
    notebook_id: UUID
    text: str | None = None
    source_ids: Sequence[UUID] | None = None
    anchor: AnchorPassages | AnchorText | None = None
    web_search: bool = False  # search the web for this question (spends a search)
    actor: Actor | None = None  # whose role picks the daily search limit


@dataclass(frozen=True, slots=True)
class Turn:
    """The question to answer and the thread before it."""

    text: str
    source_ids: Sequence[UUID] | None  # None = the persisted selection
    anchor: AnchorPassages | AnchorText | None
    history: list[NotebookMessage]  # earlier messages, oldest first
    user_message: NotebookMessage | None = None  # regenerate: the stored question
    replaces: NotebookMessage | None = None  # regenerate: the answer to replace
    web_search: bool = False  # a new question asked with the web toggle on
    web: list[WebResult] = field(default_factory=list)  # regenerate: the same pages
    summary: str | None = None  # older turns, compacted (AI-EFF-2)


@dataclass(frozen=True, slots=True)
class Prepared:
    """A turn ready for the model."""

    user_id: UUID
    notebook_id: UUID
    turn: Turn
    selected: list[UUID]  # the usable sources of the question, by position
    pack: ContextPack
    system: str
    messages: list[dict[str, Any]]
    max_tokens: int
    chars: int  # size of the prompt
    web: list[WebResult] = field(default_factory=list)  # pages the model was given
    course: bool = False  # a course workspace: the course pool pays


@dataclass(frozen=True, slots=True)
class Outcome:
    """What is stored for the assistant message."""

    text: str
    citations: list[Citation]
    followups: list[str]
    grounded: bool
    usage: Usage
    model: str
    action: dict[str, Any] | None = None
    stopped: bool = False
    web: list[WebResult] = field(default_factory=list)


@dataclass(slots=True)
class Streamed:
    """What a stream has produced so far."""

    raw: list[str] = field(default_factory=list)  # the model's text
    sent: list[str] = field(default_factory=list)  # text events handed out
    citations: list[Citation] = field(default_factory=list)  # citation events
    usage: Usage | None = None
    stored: bool = False  # the finished answer is in the database

    def take(self, piece: StreamPiece) -> StreamEvent:
        """Turn a piece into its event and remember that it goes out."""
        if isinstance(piece, CitationPiece):
            self.citations.append(piece.citation)
            return StreamEvent("citation", piece.citation.model_dump(mode="json"))
        self.sent.append(piece.text)
        return StreamEvent("delta", {"text": piece.text})


def _chars(system: str, messages: Sequence[dict[str, Any]]) -> int:
    """Characters of the prompt (message content is text or a list of parts)."""
    total = len(system)
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            total += len(content)
        else:
            total += sum(len(str(part.get("text", ""))) for part in content)
    return total


def _previous_user_text(history: Sequence[NotebookMessage]) -> str | None:
    """The student's last question before this one (it helps short follow-ups)."""
    for message in reversed(history):
        if message.role is MessageRole.USER:
            return message.content.text
    return None


def _anchor_labels(
    pack: ContextPack, anchor: AnchorPassages | AnchorText | None
) -> list[str]:
    """Labels, in this request, of the passages the student pinned."""
    if not isinstance(anchor, AnchorPassages):
        return []
    pinned = set(anchor.ids)
    return [
        label for label, passage in pack.labels.items() if passage.passage_id in pinned
    ]


class AnswerPipeline:
    """Answers one question of a notebook chat, as a whole or as a stream."""

    def __init__(self, core: NotebooksCore) -> None:
        """Store the shared services of the module."""
        self.core = core

    # - - - admission (before the lock) - - -

    async def admit_question(self, user_id: UUID, notebook_id: UUID, text: str) -> str:
        """Access check (404), question check (422), rate limit (429).

        Asking reads the notebook: a course member who may only read can ask too
        (in their own thread, paid from their own budget).

        Returns:
            The trimmed question.
        """
        course = await self._require_access(user_id, notebook_id)
        clean = clean_question(text)
        await self._rate_limit(user_id, course=course)
        return clean

    async def admit_regeneration(self, user_id: UUID, notebook_id: UUID) -> None:
        """Access check (404) and rate limit (429)."""
        course = await self._require_access(user_id, notebook_id)
        await self._rate_limit(user_id, course=course)

    async def _require_access(self, user_id: UUID, notebook_id: UUID) -> bool:
        """Check that the user may read the notebook; True for a course workspace."""
        async with self.core.uow_factory() as uow:
            notebook = await load_notebook(uow, user_id, notebook_id, write=False)
        return notebook.is_course_workspace

    async def _rate_limit(self, user_id: UUID, *, course: bool) -> None:
        """Questions per minute of the user (course staff have their own limit)."""
        deps = self.core.deps
        limits = await deps.effective_limits.current()
        await deps.rate_limiter.hit(
            f"lms-chat:{user_id}" if course else f"nb-chat:{user_id}",
            limit=(
                limits.lms_ai_chat_per_minute if course else limits.nb_chat_per_minute
            ),
            window_seconds=RATE_WINDOW_SECONDS,
        )

    # - - - one answer - - -

    async def answer(self, request: AnswerRequest) -> TurnView:
        """Answer in one piece: both messages are stored in one transaction."""
        with recording(StepRecorder()):  # AI-STEPS: stored with the answer
            return await self._answer(request)

    async def stream(self, request: AnswerRequest) -> AsyncGenerator[StreamEvent, None]:
        """Answer as events; the steps of the answer stream as ``step`` events."""
        with recording(StepRecorder()):
            async with aclosing(self._stream(request)) as events:
                async for event in events:
                    yield event

    async def _answer(self, request: AnswerRequest) -> TurnView:
        async with self.core.turn_lock.hold(request.notebook_id, request.user_id):
            prepared = await self._prepare(request)
            completion = await self.core.llm.text(
                system=prepared.system,
                messages=prepared.messages,
                max_tokens=prepared.max_tokens,
            )
            raw = await self._openui(completion.text)
            parsed = process_answer(raw, prepared.pack)
            outcome = _outcome(
                parsed, raw, completion.usage, completion.model, prepared.web
            )
            return await self._settle(prepared, outcome, None)

    async def _stream(
        self, request: AnswerRequest
    ) -> AsyncGenerator[StreamEvent, None]:
        """Answer as events: ``message``, ``delta`` and ``citation``, then ``done``.

        Failures before the question is stored are raised (nothing was stored; the
        caller reads the first event before it answers 200). Later failures end the
        stream with an ``error`` event. When the consumer stops early the partial
        answer is stored with ``stopped=True`` and the budget is charged.
        """
        async with self.core.turn_lock.hold(request.notebook_id, request.user_id):
            prepared = await self._prepare(request)
            question = prepared.turn.user_message or await self._store_user(prepared)
            streamed = Streamed()
            try:
                yield StreamEvent(
                    "message", {"id": str(question.id), "seq": question.seq}
                )
                if prepared.web:
                    yield _web_event(prepared.web)
                for update in _step_events():
                    yield update
                model = _with_steps(self._model_events(prepared, streamed))
                async with aclosing(model) as events:
                    async for event in events:
                        yield event
                done = await self._finish(prepared, streamed, question)
            except (GeneratorExit, asyncio.CancelledError):
                await self._stop(prepared, streamed, question)
                raise
            except Exception as exc:  # every failure becomes an event
                yield self._error_event(exc)
                return
            yield done

    async def _model_events(
        self, prepared: Prepared, streamed: Streamed
    ) -> AsyncGenerator[StreamEvent, None]:
        """Call the model and yield the events that are safe to show."""
        citing = StreamingAnswer(prepared.pack)
        markers = WebMarkers(len(prepared.web)) if prepared.web else None
        call = self.core.llm.stream(
            system=prepared.system,
            messages=prepared.messages,
            max_tokens=prepared.max_tokens,
        )
        async with aclosing(cast("AsyncGenerator[StreamItem, None]", call)) as items:
            async for item in items:
                if item.usage is not None:
                    streamed.usage = item.usage
                delta = item.delta or ""
                streamed.raw.append(delta)
                for piece in citing.feed(delta):
                    if (shown := _through_web(piece, markers)) is not None:
                        yield streamed.take(shown)
        for piece in citing.flush():
            if (shown := _through_web(piece, markers)) is not None:
                yield streamed.take(shown)
        if markers is not None and (rest := markers.flush()):
            yield streamed.take(DeltaPiece(rest))

    async def _finish(
        self, prepared: Prepared, streamed: Streamed, question: NotebookMessage
    ) -> StreamEvent:
        """Store the finished answer and build the ``done`` event."""
        raw = await self._openui("".join(streamed.raw))
        parsed = process_answer(raw, prepared.pack)
        usage = streamed.usage or _estimated_usage(prepared, raw)
        outcome = _outcome(parsed, raw, usage, self.core.llm.model(), prepared.web)
        view = await self._settle(prepared, outcome, question, streamed)
        return StreamEvent(
            "done",
            {
                "message": message_payload(view.assistant_message),
                "usage": usage_payload(view.usage),
                "action": view.action,
            },
        )

    async def _stop(
        self, prepared: Prepared, streamed: Streamed, question: NotebookMessage
    ) -> None:
        """Keep what the student saw: a stopped answer in a fresh transaction."""
        if streamed.stored:
            return
        outcome = _stopped_outcome(prepared, streamed, self.core.llm.model())
        try:
            await asyncio.shield(self._record(prepared, outcome, question))
        except Exception:  # closing must not fail
            log.error(
                "notebooks_stop_not_stored", notebook_id=str(prepared.notebook_id)
            )

    def _error_event(self, exc: Exception) -> StreamEvent:
        """The problem fields of an error (``common/internal`` for a crash)."""
        if isinstance(exc, BaseError):
            log.info("notebooks_stream_error", code=exc.code)
            title = self.core.deps.i18n.t("en", exc.message_key, **exc.params)
            return StreamEvent(
                "error",
                {
                    "type": exc.code,
                    "title": title,
                    "message_key": exc.message_key,
                    "params": dict(exc.params),
                },
            )
        log.error(
            "notebooks_stream_failed", error_type=type(exc).__name__, exc_info=exc
        )
        return StreamEvent(
            "error",
            {
                "type": "common/internal",
                "title": "Internal Server Error",
                "message_key": "error-internal",
                "params": {},
            },
        )

    # - - - reading: question, sources, context, prompt - - -

    async def _prepare(self, request: AnswerRequest) -> Prepared:
        """Read the context and build the prompt; refuse what the budget cannot pay."""
        user_id, notebook_id = request.user_id, request.notebook_id
        async with self.core.uow_factory() as uow:
            notebook = await load_notebook(uow, user_id, notebook_id, write=False)
            # Refused before the source embeddings and retrieval below run.
            await self.core.budget.pool(notebook.is_course_workspace).require_access(
                user_id
            )
            turn = await self._turn(uow, request)
            sources = await self._sources(uow, notebook_id, turn.source_ids)
            pack = await self.core.context.for_chat(
                uow,
                notebook_id,
                sources,
                question=turn.text,
                previous_user_text=_previous_user_text(turn.history),
                anchor=turn.anchor,
            )
        turn = await self._compacted(request, turn)
        course = await self.core.course_context.load(notebook)
        if course is not None:
            pack = replace(pack, course=course)
        locale = await self.core.locale.locale_of(user_id)
        system = self._system(notebook.chat_config, locale, course)
        school = await self._school_facts(request, turn, pack)
        messages = self._messages(pack, turn, [], school)
        max_tokens = self.core.llm.max_tokens(
            AiTask.NOTEBOOK_CHAT, MAX_TOKENS[notebook.chat_config.length]
        )
        wants_web = turn.web_search or bool(turn.web)
        reserve = WEB_RESERVE_CHARS if wants_web else 0
        chars = _chars(system, messages) + reserve
        pool = self.core.budget.pool(notebook.is_course_workspace)
        await pool.require(user_id, estimate_cost(chars, max_tokens))
        web = turn.web or (await self._search(request, turn, locale))
        if web:  # the same pages again on a regeneration, a new search otherwise
            messages = self._messages(pack, turn, web, school)
            chars = _chars(system, messages)
        return Prepared(
            user_id=user_id,
            notebook_id=notebook_id,
            turn=turn,
            selected=[source.id for source in sources],
            pack=pack,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            chars=chars,
            web=web,
            course=notebook.is_course_workspace,
        )

    async def _school_facts(
        self, request: AnswerRequest, turn: Turn, pack: ContextPack
    ) -> str | None:
        """School facts for a question without sources (None: nothing to add)."""
        knowledge = self.core.school_knowledge
        if knowledge is None or pack.sources:
            return None
        return await knowledge.block_for(
            turn.text, notebook_id=request.notebook_id, actor=request.actor
        )

    async def _search(
        self, request: AnswerRequest, turn: Turn, locale: str
    ) -> list[WebResult]:
        """The numbered pages of a new question's web search; none when it is off.

        The search is paid before the model answers; it is not given back if the
        answer then fails (the pages were found).
        """
        if not turn.web_search:
            return []
        api = self.core.web_search
        if api is None:
            raise WebSearchDisabledError()
        actor = request.actor or Actor(
            user_id=request.user_id, roles=frozenset({Role.STUDENT})
        )
        async with step(StepKind.WEB_SEARCH, "Searched the web"):
            outcome = await api.search(
                actor, query=turn.text, locale=locale, kind="chat"
            )
        return numbered(outcome.hits)

    async def _history_span(self) -> int:
        """Messages read for a turn: the history limit and the older ones to compact."""
        return await history_limit(self.core.deps.effective_limits) + COMPACT_LOOKBACK

    async def _compacted(self, request: AnswerRequest, turn: Turn) -> Turn:
        """The newest messages in full and a summary of the older ones (AI-EFF-2)."""
        limit = await history_limit(self.core.deps.effective_limits)
        compactor = self.core.compactor
        if compactor is None:
            history, summary = window_only(turn.history, limit)
        else:
            history, summary = await compactor.apply(
                request.notebook_id, request.user_id, turn.history, limit=limit
            )
        return replace(turn, history=history, summary=summary)

    async def _turn(self, uow: NotebooksUnitOfWork, request: AnswerRequest) -> Turn:
        """The question and the thread before it (a new question or the last one)."""
        user_id, notebook_id = request.user_id, request.notebook_id
        if request.text is not None:
            span = await self._history_span()
            tail = await uow.messages.list_tail(notebook_id, user_id, span)
            return Turn(
                request.text,
                request.source_ids,
                request.anchor,
                tail,
                web_search=request.web_search,
            )
        span = await self._history_span()
        tail = await uow.messages.list_tail(notebook_id, user_id, span + 2)
        if (
            len(tail) < 2
            or tail[-1].role is not MessageRole.ASSISTANT
            or tail[-2].role is not MessageRole.USER
        ):
            raise InvalidOptionsError(params={"reason": "nothing-to-regenerate"})
        question, old = tail[-2], tail[-1]
        content = question.content
        return Turn(
            content.text,
            content.source_ids,
            content.anchor,
            tail[:-2],
            question,
            old,
            web=[item.model_copy(update={"cited": False}) for item in old.content.web],
        )

    async def _sources(
        self,
        uow: NotebooksUnitOfWork,
        notebook_id: UUID,
        requested: Sequence[UUID] | None,
    ) -> list[Source]:
        """The usable sources of this notebook for the question, by position."""
        everything = await uow.sources.list_for_notebook(notebook_id)
        wanted = None if requested is None else set(requested)
        modalities = self.core.deps.settings.ai_profile(AiTask.NOTEBOOK_CHAT).modalities
        chosen = [
            source
            for source in everything
            if source.usable
            and readable_by(source, modalities)
            and (source.selected if wanted is None else source.id in wanted)
        ]
        if not chosen and (wanted or any(s.selected for s in everything)):
            raise NoSourcesSelectedError()  # picked, but none is ready to read
        return chosen  # empty: a general answer, not grounded in the materials

    async def _openui(self, raw: str) -> str:
        """AI-OPENUI: the answer with broken OpenUI blocks repaired or dropped."""
        if self.core.openui is None:
            return raw
        return await self.core.openui.finalize(raw)

    def _system(
        self, config: ChatConfig, locale: str, course: CourseContext | None = None
    ) -> str:
        """The grounded system prompt of the notebook's chat settings."""
        prompt = chat_system_prompt(
            language=resolve_language(config.language.value, locale),
            style=config.style,
            custom_prompt=config.custom_prompt,
            length=config.length,
            goal=config.goal,
            today=local_today(self.core.deps.clock),
            course=course,
        )
        if self.core.deps.settings.ai.openui_enabled:  # AI-OPENUI
            prompt += openui_prompt()
        return prompt

    def _messages(
        self,
        pack: ContextPack,
        turn: Turn,
        web: list[WebResult],
        school: str | None = None,
    ) -> list[dict[str, Any]]:
        """Context message, the last turns, then the question (§ 3.3.3).

        With web results the question message ends with their block.
        """
        anchor_text = turn.anchor.text if isinstance(turn.anchor, AnchorText) else None
        note = anchor_note(_anchor_labels(pack, turn.anchor), anchor_text)
        question = question_message(turn.text, note)
        if not pack.sources:
            question = f"{NO_SOURCES_NOTE}\n\n{question}"
            if school:
                question = f"{school}\n\n{question}"
        block = render_web_block(web, full=True, intro=WEB_INTRO)
        return [
            self.core.llm.context_message(
                render_sources_block(pack), extra=summary_note(turn.summary)
            ),
            *history_messages(turn.history, limit=len(turn.history)),
            {
                "role": "user",
                "content": f"{question}\n\n{block}" if block else question,
            },
        ]

    # - - - writing - - -

    async def _store_user(self, prepared: Prepared) -> NotebookMessage:
        """Store the question alone (a stream does it first)."""
        async with self.core.uow_factory() as uow:
            message = await self._add_user(uow, prepared)
            await uow.commit()
        return message

    async def _add_user(
        self, uow: NotebooksUnitOfWork, prepared: Prepared
    ) -> NotebookMessage:
        turn = prepared.turn
        seq = await uow.messages.last_seq(prepared.notebook_id, prepared.user_id)
        message = NotebookMessage(
            id=new_id(),
            notebook_id=prepared.notebook_id,
            user_id=prepared.user_id,
            seq=seq + 1,
            role=MessageRole.USER,
            content=MessageContent(
                text=turn.text, anchor=turn.anchor, source_ids=prepared.selected
            ),
            created_at=self.core.deps.clock.now(),
        )
        await uow.messages.add(message)
        return message

    async def _store(
        self, prepared: Prepared, outcome: Outcome, question: NotebookMessage | None
    ) -> tuple[NotebookMessage, NotebookMessage]:
        """Store the answer (and the question, if it is new) in one transaction."""
        async with self.core.uow_factory() as uow:
            known = (
                question
                or prepared.turn.user_message
                or await self._add_user(uow, prepared)
            )
            if prepared.turn.replaces is not None:
                await uow.messages.delete(prepared.turn.replaces.id)
            seq = await uow.messages.last_seq(prepared.notebook_id, prepared.user_id)
            answer = self._assistant(prepared, outcome, seq + 1)
            await uow.messages.add(answer)
            await uow.commit()
        return known, answer

    def _assistant(
        self, prepared: Prepared, outcome: Outcome, seq: int
    ) -> NotebookMessage:
        pack, usage = prepared.pack, outcome.usage
        return NotebookMessage(
            id=new_id(),
            notebook_id=prepared.notebook_id,
            user_id=prepared.user_id,
            seq=seq,
            role=MessageRole.ASSISTANT,
            content=MessageContent(
                text=outcome.text,
                citations=outcome.citations,
                followups=outcome.followups,
                source_ids=[source.source_id for source in pack.sources],
                retrieval=pack.retrieval,
                grounded=outcome.grounded,
                web=outcome.web,
                steps=_recorded_steps(),
            ),
            created_at=self.core.deps.clock.now(),
            tokens_in=usage.input,
            tokens_out=usage.output,
            tokens_cached=usage.cached,
            weighted=usage.weighted,
            model=outcome.model,
            stopped=outcome.stopped,
        )

    async def _record(
        self, prepared: Prepared, outcome: Outcome, question: NotebookMessage | None
    ) -> tuple[NotebookMessage, NotebookMessage]:
        """Store the messages, then count the weighted tokens in the budget."""
        known, answer = await self._store(prepared, outcome, question)
        pool = self.core.budget.pool(prepared.course)
        await pool.add(prepared.user_id, outcome.usage.weighted)
        log.info(
            "notebooks_answer",
            notebook_id=str(prepared.notebook_id),
            mode=prepared.pack.mode,
            sources=len(prepared.pack.sources),
            tokens_in=outcome.usage.input,
            tokens_out=outcome.usage.output,
            tokens_cached=outcome.usage.cached,
            weighted=outcome.usage.weighted,
            citations=len(outcome.citations),
            stopped=outcome.stopped,
        )
        return known, answer

    async def _settle(
        self,
        prepared: Prepared,
        outcome: Outcome,
        question: NotebookMessage | None,
        streamed: Streamed | None = None,
    ) -> TurnView:
        """Record a finished answer and return it with the fresh usage.

        A stream is marked as stored as soon as the answer is, so that a late
        cancellation does not store a stopped copy.
        """
        known, answer = await self._record(prepared, outcome, question)
        if streamed is not None:
            streamed.stored = True
        usage = await self.core.usage.execute(prepared.user_id, course=prepared.course)
        return TurnView(known, answer, usage, outcome.action)


def _step_events() -> list[StreamEvent]:
    """The ``step`` events of the steps started or finished since the last call."""
    recorder = current_steps()
    if recorder is None:
        return []
    return [
        StreamEvent("step", item.model_dump(mode="json"))
        for item in recorder.pop_updates()
    ]


async def _with_steps(
    events: AsyncGenerator[StreamEvent, None],
) -> AsyncGenerator[StreamEvent, None]:
    """The model's events, each followed by the steps recorded meanwhile."""
    async with aclosing(events) as inner:
        async for event in inner:
            yield event
            for update in _step_events():
                yield update
    for update in _step_events():  # the steps of the last chunk
        yield update


def _recorded_steps() -> list[AgentStep]:
    """The steps of the answer being made (AI-STEPS)."""
    recorder = current_steps()
    return recorder.steps if recorder is not None else []


def _web_event(web: list[WebResult]) -> StreamEvent:
    """The ``web`` event: the pages the answer may cite, before its first delta."""
    return StreamEvent(
        "web",
        {
            "results": [
                item.model_dump(mode="json", exclude={"published_date"}) for item in web
            ]
        },
    )


def _through_web(piece: StreamPiece, markers: WebMarkers | None) -> StreamPiece | None:
    """Turn the ``[[W1]]`` markers of a text piece into chips (None: all held back)."""
    if markers is None or not isinstance(piece, DeltaPiece):
        return piece
    text = markers.feed(piece.text)
    return DeltaPiece(text) if text else None


def _mark_cited(web: list[WebResult], used: list[int]) -> list[WebResult]:
    return [item.model_copy(update={"cited": item.n in used}) for item in web]


def _outcome(
    answer: ProcessedAnswer,
    raw: str,
    usage: Usage,
    model: str,
    web: list[WebResult],
) -> Outcome:
    """The finished answer with the Studio action the model proposed, if any.

    Web markers become chips here; an answer that cites only web pages is grounded.
    """
    text, used = rewrite_markers(answer.text, len(web)) if web else (answer.text, [])
    return Outcome(
        text=text,
        citations=answer.citations,
        followups=answer.followups,
        grounded=answer.grounded or bool(used),
        usage=usage,
        model=model,
        action=split_action(raw)[1],
        web=_mark_cited(web, used),
    )


def _estimated_usage(prepared: Prepared, text: str) -> Usage:
    """Usage when the provider sent none: the prompt and the text, by estimate."""
    return Usage(
        input=estimate_tokens(prepared.chars), output=estimate_tokens(len(text))
    )


def _stopped_outcome(prepared: Prepared, streamed: Streamed, model: str) -> Outcome:
    """The partial answer the student saw, with the citations its text uses."""
    text = "".join(streamed.sent).rstrip()
    used = {n for chip in _CHIP.findall(text) for n in chip.split(",") if n}
    citations = [item for item in streamed.citations if str(item.n) in used]
    usage = streamed.usage or _estimated_usage(prepared, "".join(streamed.raw))
    used_web = cited_in(text)
    return Outcome(
        text=text,
        citations=citations,
        followups=[],
        grounded=bool(citations) or bool(used_web),
        usage=usage,
        model=model,
        stopped=True,
        web=_mark_cited(prepared.web, used_web),
    )
