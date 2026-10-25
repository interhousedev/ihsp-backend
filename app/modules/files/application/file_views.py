"""FileView: a file plus the computed fields the API shows."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.modules.files.domain.policy import FilesLimits, expiry_date
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.domain.used_by import UsedBy
from app.modules.files.ports.term_resolver import TermResolver
from app.modules.files.ports.usage_resolver import UsageResolver
from app.shared.clock import to_local
from app.shared.contracts.files import FileScope


@dataclass(frozen=True, slots=True)
class FileView:
    """A file with its expiry date, usage and assistant readiness."""

    file: StoredFile
    expires_on: date | None
    used_by: list[UsedBy]
    assistant_ready: bool


class FileViewBuilder:
    """Builds FileViews: term end dates and usage are looked up once per batch."""

    def __init__(
        self, terms: TermResolver, usage: UsageResolver, limits: FilesLimits
    ) -> None:
        """Store the resolvers and limits."""
        self._terms = terms
        self._usage = usage
        self._limits = limits

    async def expires_on(
        self, file: StoredFile, cache: dict[UUID, date | None]
    ) -> date | None:
        """Return the last day the file is kept, if it is known."""
        if file.expires_at is not None:
            return to_local(file.expires_at).date()
        if file.scope != FileScope.STUDENT or file.term_id is None:
            return None
        if file.term_id not in cache:
            end = await self._terms.term_end(file.term_id)
            cache[file.term_id] = None if end is None else expiry_date(end)
        return cache[file.term_id]

    def assistant_ready(self, file: StoredFile) -> bool:
        """True when the extracted text is small enough for the assistant."""
        return (
            file.text_bytes is not None
            and file.text_bytes <= self._limits.ai_text_max_bytes
        )

    async def build(
        self, files: Sequence[StoredFile], *, with_usage: bool = True
    ) -> list[FileView]:
        """Return views in the order of the files."""
        usage = (
            await self._usage.used_by([file.id for file in files])
            if with_usage and files
            else {}
        )
        cache: dict[UUID, date | None] = {}
        return [
            FileView(
                file=file,
                expires_on=await self.expires_on(file, cache),
                used_by=usage.get(file.id, []),
                assistant_ready=self.assistant_ready(file),
            )
            for file in files
        ]

    async def build_one(self, file: StoredFile) -> FileView:
        """Return the view of one file."""
        return (await self.build([file]))[0]
