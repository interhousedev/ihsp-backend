"""Job `notebooks.extract_source_vision`: the model reads a scanned file (re-read)."""

import base64
from datetime import datetime
from functools import partial
from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.application.light_json import LightJson
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.owner_usage import owner_usage
from app.modules.notebooks.application.readers.file_reader import file_id_of
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind, SourceStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import (
    AiAccessRevokedError,
    AiInvalidOutputError,
    AiProviderError,
)
from app.shared.contracts.files import FilesApi
from app.shared.limits import LimitsProvider
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

MAX_PAGES: Final = 30
MAX_BYTES: Final = 20 * 1024 * 1024
MAX_TOKENS: Final = 8000
PDF: Final = "application/pdf"
IMAGE_TYPES: Final = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
TEXT_SCHEMA_NAME: Final = "source_text"
TEXT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}
SYSTEM: Final = (
    "You transcribe documents. Read every page or image of the attached file and "
    "return all readable text in reading order, as plain text without commentary. "
    "If there is no readable text, return an empty string."
)
USER: Final = "Transcribe the attached file."
TASK: Final = "notebooks.extract_source_vision"
STARTED_KEY: Final = "vision_started_at"  # in `ref`: when the model read began


def vision_started(now: datetime) -> dict[str, str]:
    """The `ref` entries that mark a source as read by the model since `now`."""
    return {STARTED_KEY: now.isoformat()}


def attachment_of(content_type: str, name: str, data: bytes) -> dict[str, Any]:
    """The OpenRouter content part that carries a PDF or an image to the model."""
    encoded = base64.b64encode(data).decode("ascii")
    if content_type == PDF:
        return {
            "type": "file",
            "file": {"filename": name, "file_data": f"data:{PDF};base64,{encoded}"},
        }
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{content_type};base64,{encoded}"},
    }


class ExtractSourceVision:
    """Reads a file source with no text layer; a failure is stored, never raised."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        files: FilesApi,
        light: LightJson,
        kicker: TaskKicker,
        limits: LimitsProvider | None = None,
    ) -> None:
        """Store the collaborators; `limits` checks the owner's AI access per run."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files
        self.light = light
        self.kicker = kicker
        self.limits = limits

    async def execute(self, source_id: UUID) -> None:
        """Read the file with the model; the source must be `processing`.

        A text found goes back through `process_source`. No text at all keeps the
        source as `ready` with no passages (the user chose to keep it).
        """
        async with self.uow_factory() as uow:
            source = await uow.sources.get(source_id)
            if source is None or source.status is not SourceStatus.PROCESSING:
                return
            notebook = await uow.notebooks.get(source.notebook_id)
            if (
                notebook is None
                or notebook.is_deleted
                or source.kind is not SourceKind.FILE
            ):
                return
        async with owner_usage(self.limits, notebook.owner_id):
            failure, text = await self._read(source, notebook)
        if failure is not None:
            await self._finish(source_id, failure=failure)
        else:
            await self._finish(source_id, text=text)

    async def _read(
        self, source: Source, notebook: Notebook
    ) -> tuple[SourceFailure | None, str]:
        """The model's text of the file, or the failure that stops it."""
        file_id = file_id_of(source)
        ref = await self.files.get(file_id) if file_id else None
        if ref is None or ref.status == "deleted":
            return SourceFailure.DELETED, ""
        if ref.content_type != PDF and ref.content_type not in IMAGE_TYPES:
            return SourceFailure.UNSUPPORTED_TYPE, ""
        if ref.byte_size > MAX_BYTES:
            return SourceFailure.TOO_LARGE, ""
        pages = await self.files.page_count(ref.id)
        if pages is not None and pages > MAX_PAGES:
            return SourceFailure.TOO_LARGE, ""
        data = await self.files.read_bytes(ref.id)
        part = attachment_of(ref.content_type, ref.name, data)
        try:
            answer = await self.light.call(
                notebook.owner_id,
                task=AiTask.SOURCE_VISION_EXTRACT,
                system=SYSTEM,
                user=USER,
                schema_name=TEXT_SCHEMA_NAME,
                schema=TEXT_SCHEMA,
                max_tokens=MAX_TOKENS,
                course=notebook.is_course_workspace,
                attachments=[part],
            )
        except AiAccessRevokedError:
            log.info("notebooks_vision_access_revoked", source_id=str(source.id))
            return SourceFailure.ACCESS_REVOKED, ""
        except (AiProviderError, AiInvalidOutputError) as error:
            log.info(
                "notebooks_vision_failed", source_id=str(source.id), error=str(error)
            )
            return SourceFailure.PROVIDER_ERROR, ""
        return None, str(answer.get("text", "")).strip()

    async def _finish(
        self,
        source_id: UUID,
        *,
        text: str = "",
        failure: SourceFailure | None = None,
    ) -> None:
        """Store the outcome; the notebook is locked first, then the source."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            current_source = await uow.sources.get(source_id)
            if current_source is None:
                return
            notebook = await uow.notebooks.get_for_update(current_source.notebook_id)
            current = await uow.sources.get_for_update(source_id)
            if (
                notebook is None
                or notebook.is_deleted
                or current is None
                or current.status is not SourceStatus.PROCESSING
            ):
                return
            current.updated_at = now
            if failure is not None:
                current.status = SourceStatus.FAILED
                current.failure = failure
            elif text:
                # The text goes to process_source, which chunks it like any other text.
                current.ref = {**current.ref, "ai_text": text}
                current.status = SourceStatus.PENDING
                current.failure = None
                uow.after_commit(
                    partial(
                        self.kicker.kick,
                        "notebooks.process_source",
                        source_id=str(current.id),
                    )
                )
            else:
                # No text at all: the source stays, with no passages (the UI badge).
                current.ref = {**current.ref, "ai_text": ""}
                current.status = SourceStatus.READY
                current.failure = None
                current.word_count = 0
                current.passage_count = 0
                current.char_count = 0
            await uow.sources.save(current)
            await sources_changed(uow, notebook, now)
            await uow.commit()
        log.info(
            "notebooks_vision_done",
            source_id=str(source_id),
            text=bool(text),
            failure=failure.value if failure else None,
        )
