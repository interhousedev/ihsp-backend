"""Import the student's CEFR and national certificates from EMIS."""

import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.entry import (
    CertificateEntry,
    EntryFile,
    EntrySource,
)
from app.modules.certificates.ports.fetcher import CertificateFetcher
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisCertificate,
    EmisSource,
    EmisUnavailable,
)
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What an import did: entries created and updated, PDFs stored, rest skipped."""

    created: int = 0
    updated: int = 0
    files: int = 0
    skipped: int = 0


class ImportEmis:
    """Upsert EMIS certificates by (student, type, serial) and store their PDFs."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        emis: EmisSource,
        files: FilesApi,
        fetcher: CertificateFetcher,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._emis = emis
        self._files = files
        self._fetcher = fetcher

    async def execute(self, student_id: UUID) -> ImportResult:
        """Read the EMIS profile and bring the student's entries up to date."""
        try:
            found = await self._emis.certificates(student_id)
        except EmisAuthFailed as exc:  # a 401 here would log the student out
            raise EmisUnavailable(support_details="EMIS login needs a refresh") from exc
        created = updated = stored = skipped = 0
        for item in found:
            outcome = await self._upsert(student_id, item)
            if outcome is None:
                skipped += 1
                continue
            entry, is_new, changed = outcome
            created += is_new
            updated += changed and not is_new
            skipped += not (is_new or changed)
            if item.url and not entry.files:
                stored += await self._store_pdf(student_id, entry, item)
        return ImportResult(created, updated, stored, skipped)

    async def _upsert(
        self, student_id: UUID, item: EmisCertificate
    ) -> tuple[CertificateEntry, bool, bool] | None:
        """Return (entry, created, changed), or None when the item cannot be kept."""
        if not item.serial:
            return None
        async with self._uow_factory() as uow:
            kind = await uow.types.get_by_code(item.kind)
            if kind is None:
                return None
            entry = await uow.entries.find_by_serial(student_id, kind.id, item.serial)
            if entry is None:
                entry = self._new_entry(student_id, kind, item)
                await uow.entries.add(entry)
                await uow.commit()
                return entry, True, False
            changed = _merge(entry, item)
            if changed:
                await uow.entries.save(entry)
                await uow.commit()
            return entry, False, changed

    def _new_entry(
        self, student_id: UUID, kind: CertificateType, item: EmisCertificate
    ) -> CertificateEntry:
        entry = CertificateEntry(
            id=new_id(),
            student_id=student_id,
            type_id=kind.id,
            created_at=self._clock.now(),
            serial=item.serial,
            source=EntrySource.EMIS,
        )
        _merge(entry, item)
        return entry

    async def _store_pdf(
        self, student_id: UUID, entry: CertificateEntry, item: EmisCertificate
    ) -> int:
        """Download the PDF and attach it; a failure only means no file (0)."""
        if item.url is None:
            return 0
        try:
            fetched = await self._fetcher.fetch(item.url)
            name = _pdf_name(item.kind, item.serial or fetched.name)
            stored = await self._files.store_bytes(
                owner_id=student_id,
                scope=FileScope.STUDENT,
                purpose=FilePurpose.CERTIFICATE,
                name=name,
                data=fetched.data,
            )
        except BaseError as exc:
            log.warning("certificate_pdf_skipped", code=exc.code, kind=item.kind)
            return 0
        file = EntryFile(
            stored.id, entry.id, stored.name, stored.byte_size, stored.content_type
        )
        async with self._uow_factory() as uow:
            await uow.entries.add_file(file)
            await uow.commit()
        entry.files.append(file)
        return 1


def _merge(entry: CertificateEntry, item: EmisCertificate) -> bool:
    """Copy the EMIS values into the entry; True if anything changed."""
    issued: date | None = item.issued_on
    values: dict[str, object] = {
        "level": item.level,
        "score": item.score,
        "percent": item.percent,
        "subject": item.subject,
        "year": issued.year if issued else None,
        "issued_at": issued,
        "expires_at": item.expires_on,
    }
    changed = False
    for key, value in values.items():
        if getattr(entry, key) != value:
            setattr(entry, key, value)
            changed = True
    return changed


def _pdf_name(kind: str, serial: str) -> str:
    cleaned = _UNSAFE_NAME.sub("-", serial).strip("-.") or "certificate"
    return f"{kind}-{cleaned}.pdf"
