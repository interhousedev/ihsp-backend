"""Job `notebooks.gather_web_materials`: the files a web source links to (§ 3.2.1).

When a web page added by its owner to a manual notebook is ready, the page is scanned
for linked documents, audio and article images (`MaterialFetcher`). A cheap model
(AI task WEB_MATERIAL_TRIAGE) keeps the substantive ones; images are looked at. A
kept file is downloaded (SSRF-safe, size and type checked), stored in the owner's
own files under their quota, and added to the same notebook as a `file` source
linked to the page (`ref.parent_source_id`). Images are described and audio is
transcribed by the media model (AI task MEDIA_DESCRIBE); that text is the source's.

Privacy: the materials belong to the one notebook and owner that gathered them.
Subject, lesson and course notebooks never gather, nothing is copied into anyone
else's notebook, and the shared web page cache (`ai.web_pages`) never holds them.
"""

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from posixpath import basename
from typing import Any, Final, Protocol
from urllib.parse import unquote, urlsplit
from uuid import UUID

from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.source_limits import ensure_capacity
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.ports.quota_store import QuotaStore
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.ports.web_materials import (
    DownloadedMaterial,
    MaterialCandidate,
    MaterialFetcher,
)
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.base_error import BaseError
from app.shared.clock import Clock, local_today
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope
from app.shared.ids import new_id
from app.shared.limits import ActorLimits, LimitsProvider
from app.shared.tasks import TaskKicker
from app.shared.usage_context import bind_usage_user, reset_usage_actor

import structlog

log = structlog.get_logger(__name__)

GATHERED: Final = "web_materials"  # daily counter of stored files
DESCRIBED: Final = "media_described"  # daily counter of media model reads
FILES_QUOTA_CODE: Final = "files/quota-exceeded"
READY_POLLS: Final = 15  # the files job extracts document text in a few seconds
READY_POLL_SECONDS: Final = 2.0
TRIAGE_TOKENS: Final = 400
DESCRIBE_TOKENS: Final = 2000
NAME_CHARS: Final = 120
ADDED: Final = "added"
SKIPPED: Final = "skipped"
_EXTENSIONS: Final = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}
_AUDIO_FORMATS: Final = {".mp3": "mp3", ".m4a": "m4a", ".ogg": "ogg", ".wav": "wav"}

TRIAGE_SYSTEM: Final = (
    "You screen files linked from a web page a student is studying. Keep only "
    "substantive educational material on the page's topic: lecture notes, papers, "
    "textbooks, worksheets, slides, data tables, diagrams, charts, maps, figures "
    "and recordings of lectures. Reject logos, decorations, stock photos, adverts, "
    "forms, price lists, privacy policies, unrelated or empty files. When unsure, "
    "reject. Answer JSON only."
)
DESCRIBE_SYSTEM: Final = (
    "Describe this image for a student's study notes: what it shows, every label, "
    "number and piece of text in it, and what it teaches. Plain prose, the "
    "language of the text on the page. Answer JSON only."
)
TRANSCRIBE_SYSTEM: Final = (
    "Transcribe this recording word for word in its own language, then add a short "
    "summary. Answer JSON only."
)
_TRIAGE_SCHEMA: Final = {
    "type": "object",
    "properties": {"keep": {"type": "array", "items": {"type": "integer"}}},
    "required": ["keep"],
    "additionalProperties": False,
}
_TEXT_SCHEMA: Final = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


class JsonModel(Protocol):
    """The structured call of a light task (`LightJson`)."""

    async def call(
        self,
        owner_id: UUID,
        *,
        task: AiTask,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        course: bool = False,
        attachments: Any = (),
    ) -> dict[str, Any]:
        """Return the model's JSON document."""
        ...


Sleep = Callable[[float], Awaitable[None]]


@dataclass(slots=True)
class GatherReport:
    """What one run did."""

    found: int = 0  # candidates the notebook does not have yet
    kept: int = 0  # accepted by the triage and stored
    added: int = 0
    stopped: str | None = None  # quota | limit | files_quota | sources


def may_gather(source: Source, notebook: Notebook) -> bool:
    """Only the owner's web page in their own manual notebook gathers materials."""
    return (
        source.kind is SourceKind.URL
        and source.status is SourceStatus.READY
        and "parent_source_id" not in source.ref
        and source.owner_id == notebook.owner_id
        and notebook.origin is NotebookOrigin.MANUAL
        and not notebook.is_deleted
    )


def _file_name(candidate: MaterialCandidate, got: DownloadedMaterial) -> str:
    name = unquote(basename(urlsplit(got.url).path)) or "material"
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    wanted = _EXTENSIONS.get(got.content_type)
    suffix = f".{extension.lower()}" if extension else ""
    if (
        wanted is not None
        and suffix != wanted
        and not (wanted == ".jpg" and suffix == ".jpeg")
    ):
        suffix = wanted
    return f"{(stem or 'material')[:NAME_CHARS]}{suffix}"


def _attachment(kind: str, name: str, got: DownloadedMaterial) -> dict[str, Any]:
    data = base64.b64encode(got.data).decode("ascii")
    if kind == "audio":
        extension = name[name.rfind(".") :].lower()
        return {
            "type": "input_audio",
            "input_audio": {
                "data": data,
                "format": _AUDIO_FORMATS.get(extension, "mp3"),
            },
        }
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{got.content_type};base64,{data}"},
    }


class GatherWebMaterials:
    """Scans, triages, stores and attaches the materials of one web source."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        files: FilesApi,
        fetcher: MaterialFetcher | None,
        model: JsonModel,
        counters: QuotaStore,
        limits: LimitsProvider,
        kicker: TaskKicker,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        """Store the collaborators (no fetcher: web pages are off, nothing gathers)."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.files = files
        self.fetcher = fetcher
        self.model = model
        self.counters = counters
        self.limits = limits
        self.kicker = kicker
        self.sleep = sleep

    async def execute(self, source_id: UUID) -> GatherReport:
        """Gather once; a repeated run skips the files the notebook already has."""
        cfg = self.settings.notebooks
        report = GatherReport()
        if (
            not cfg.web_materials_enabled
            or cfg.web_materials_per_page <= 0
            or self.fetcher is None
        ):
            return report
        async with self.uow_factory() as uow:
            source = await uow.sources.get(source_id)
            notebook = await uow.notebooks.get(source.notebook_id) if source else None
        if source is None or notebook is None or not may_gather(source, notebook):
            return report
        view = await self.limits.for_user(notebook.owner_id)
        token = bind_usage_user(notebook.owner_id, unlimited=view.unlimited)
        try:
            await self._gather(self.fetcher, source, notebook, view, report)
        finally:
            reset_usage_actor(token)
        log.info(
            "notebooks_web_materials_gathered",
            source_id=str(source_id),
            found=report.found,
            kept=report.kept,
            added=report.added,
            stopped=report.stopped,
        )
        return report

    # - - - Steps - - -

    async def _gather(
        self,
        fetcher: MaterialFetcher,
        source: Source,
        notebook: Notebook,
        view: ActorLimits,
        report: GatherReport,
    ) -> None:
        cfg = self.settings.notebooks
        found = await fetcher.candidates(
            str(source.ref["url"]), cfg.web_materials_per_page
        )
        fresh = await self._unknown(notebook.id, found)
        report.found = len(fresh)
        if not fresh:
            return
        texts = [c for c in fresh if c.kind != "image"]
        wanted = set(await self._triage_texts(notebook.owner_id, source, texts))
        for candidate in fresh:
            if candidate.kind != "image" and candidate.url not in wanted:
                continue
            outcome = await self._one(fetcher, source, notebook, view, candidate)
            if outcome == ADDED:
                report.kept += 1
                report.added += 1
            elif outcome != SKIPPED:
                report.stopped = outcome
                return

    async def _one(
        self,
        fetcher: MaterialFetcher,
        source: Source,
        notebook: Notebook,
        view: ActorLimits,
        candidate: MaterialCandidate,
    ) -> str:
        """Download, check and keep one candidate: `added`, `skipped` or a stop."""
        owner = notebook.owner_id
        if not await self._room(owner, GATHERED, view.nb_web_materials_per_day):
            return "limit"
        try:
            got = await fetcher.download(
                candidate.url, self.settings.notebooks.web_materials_max_bytes
            )
        except SourceReadError as error:
            log.info("notebooks_web_material_skipped", failure=error.failure)
            return SKIPPED
        if candidate.kind == "image" and not await self._triage_image(
            owner, source, candidate, got
        ):
            return SKIPPED
        return await self._keep(source, notebook, view, candidate, got)

    async def _unknown(
        self, notebook_id: UUID, found: list[MaterialCandidate]
    ) -> list[MaterialCandidate]:
        async with self.uow_factory() as uow:
            return [
                c
                for c in found
                if not await uow.sources.ref_key_exists(notebook_id, _key(c.url))
            ]

    async def _room(self, owner: UUID, counter: str, limit: int | None) -> bool:
        if limit is None:
            return True
        used = await self.counters.used(owner, local_today(self.clock), counter)
        return used < limit

    async def _count(self, owner: UUID, counter: str) -> None:
        await self.counters.add(owner, local_today(self.clock), counter)

    async def _triage_texts(
        self, owner: UUID, source: Source, candidates: list[MaterialCandidate]
    ) -> list[str]:
        """The URLs of the documents and recordings worth keeping (one call)."""
        if not candidates:
            return []
        lines = [
            f"{index}. [{c.kind}] {c.title} | {c.url} | near: {c.context}"
            for index, c in enumerate(candidates)
        ]
        user = (
            f"Page: {source.title} ({source.ref.get('url')})\nCandidates:\n"
            + "\n".join(lines)
            + '\nReturn {"keep": [numbers of the files to keep]}.'
        )
        answer = await self._ask(
            owner, AiTask.WEB_MATERIAL_TRIAGE, TRIAGE_SYSTEM, user, _TRIAGE_SCHEMA
        )
        keep = answer.get("keep") if answer else None
        if not isinstance(keep, list):
            return []
        return [
            candidates[i].url
            for i in keep
            if isinstance(i, int) and 0 <= i < len(candidates)
        ]

    async def _triage_image(
        self,
        owner: UUID,
        source: Source,
        candidate: MaterialCandidate,
        got: DownloadedMaterial,
    ) -> bool:
        user = (
            f"Page: {source.title} ({source.ref.get('url')})\n0. [image] "
            f"{candidate.title} | {candidate.url} | near: {candidate.context}\n"
            'The image is attached. Return {"keep": [0]} to keep it, else '
            '{"keep": []}.'
        )
        answer = await self._ask(
            owner,
            AiTask.WEB_MATERIAL_TRIAGE,
            TRIAGE_SYSTEM,
            user,
            _TRIAGE_SCHEMA,
            attachments=[_attachment("image", "", got)],
        )
        keep = answer.get("keep") if answer else None
        return isinstance(keep, list) and 0 in keep

    async def _ask(
        self,
        owner: UUID,
        task: AiTask,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        attachments: list[dict[str, Any]] | None = None,
        max_tokens: int = TRIAGE_TOKENS,
    ) -> dict[str, Any] | None:
        """One model call; a provider failure or a spent budget answers nothing."""
        try:
            return await self.model.call(
                owner,
                task=task,
                system=system,
                user=user,
                schema_name=task.value,
                schema=schema,
                max_tokens=max_tokens,
                attachments=attachments or (),
            )
        except (AiProviderError, BaseError) as error:
            log.info("notebooks_web_material_model_failed", error=type(error).__name__)
            return None

    async def _keep(
        self,
        source: Source,
        notebook: Notebook,
        view: ActorLimits,
        candidate: MaterialCandidate,
        got: DownloadedMaterial,
    ) -> str:
        """Store and attach one accepted file: `added`, `skipped` or a stop."""
        name = _file_name(candidate, got)
        body: str | None = None
        if candidate.kind in ("image", "audio"):
            body = await self._media_text(notebook.owner_id, view, candidate, name, got)
            if body is None:  # not described, or the media reads of today are spent
                return SKIPPED
        if not await self._fits(notebook, len(body or "")):
            return "sources"
        try:
            ref = await self.files.store_bytes(
                owner_id=notebook.owner_id,
                scope=FileScope.STAFF if view.unlimited else FileScope.STUDENT,
                purpose=FilePurpose.AI_UPLOAD,
                name=name,
                data=got.data,
            )
        except BaseError as error:
            if error.code == FILES_QUOTA_CODE:
                return "files_quota"
            log.info("notebooks_web_material_refused", code=error.code)
            return SKIPPED
        await self._count(notebook.owner_id, GATHERED)
        if body is None and not await self._has_text(ref):
            return SKIPPED
        return await self._attach(source, notebook, candidate, ref, body)

    async def _media_text(
        self,
        owner: UUID,
        view: ActorLimits,
        candidate: MaterialCandidate,
        name: str,
        got: DownloadedMaterial,
    ) -> str | None:
        """The description or transcript (counted); None when there is none."""
        if not await self._room(owner, DESCRIBED, view.nb_media_described_per_day):
            return None
        body = await self._describe(owner, candidate, name, got)
        await self._count(owner, DESCRIBED)
        return body

    async def _describe(
        self,
        owner: UUID,
        candidate: MaterialCandidate,
        name: str,
        got: DownloadedMaterial,
    ) -> str | None:
        audio = candidate.kind == "audio"
        user = (
            f"File: {candidate.title} ({candidate.url})\nOn the page near it: "
            f'{candidate.context}\nReturn {{"text": "..."}}.'
        )
        answer = await self._ask(
            owner,
            AiTask.MEDIA_DESCRIBE,
            TRANSCRIBE_SYSTEM if audio else DESCRIBE_SYSTEM,
            user,
            _TEXT_SCHEMA,
            attachments=[_attachment(candidate.kind, name, got)],
            max_tokens=DESCRIBE_TOKENS * (4 if audio else 1),
        )
        text = answer.get("text") if answer else None
        if not isinstance(text, str) or not text.strip():
            return None
        return f"{candidate.title}\n\n{text.strip()}"

    async def _fits(self, notebook: Notebook, chars: int) -> bool:
        async with self.uow_factory() as uow:
            try:
                await ensure_capacity(uow, notebook, chars, self.settings)
            except BaseError:
                return False
        return True

    async def _has_text(self, ref: FileRef) -> bool:
        """Wait for the files job to extract the document's text."""
        for _ in range(READY_POLLS):
            current = await self.files.get(ref.id)
            if current is None or current.status in ("rejected", "deleted"):
                return False
            if current.status == "ready":
                return current.text_bytes is not None
            await self.sleep(READY_POLL_SECONDS)
        return False

    async def _attach(
        self,
        parent: Source,
        notebook: Notebook,
        candidate: MaterialCandidate,
        ref: FileRef,
        body: str | None,
    ) -> str:
        now = self.clock.now()
        async with self.uow_factory() as uow:
            current = await uow.notebooks.get_for_update(notebook.id)
            if current is None or current.is_deleted:
                return "sources"
            try:
                await ensure_capacity(uow, current, len(body or ""), self.settings)
            except BaseError:
                return "sources"
            source = Source(
                id=new_id(),
                notebook_id=current.id,
                owner_id=current.owner_id,
                kind=SourceKind.FILE,
                title=(candidate.title or ref.name)[:255],
                position=await uow.sources.next_position(current.id),
                created_at=now,
                updated_at=now,
                ref={
                    "file_id": str(ref.id),
                    "content_type": ref.content_type,
                    "parent_source_id": str(parent.id),
                    "material_url": candidate.url,
                    "media": body is not None,
                },
                ref_key=_key(candidate.url),
                origin={"kind": "web_material", "parent_source_id": str(parent.id)},
                selected=True,
                status=SourceStatus.PENDING,
                body_md=body,
            )
            await uow.sources.add(source)
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )
            await sources_changed(uow, current, now)
            await uow.commit()
        return ADDED


def _key(url: str) -> str:
    return f"material:{url}"
