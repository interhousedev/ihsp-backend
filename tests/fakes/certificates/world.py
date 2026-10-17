"""Fake neighbours of the certificates module: files, students, EMIS, downloads."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.certificates.domain.errors import CertificateDownloadError
from app.modules.certificates.ports.fetcher import FetchedFile
from app.modules.certificates.ports.student_directory import GroupInfo, StudentInfo
from app.modules.files.domain.errors import QuotaExceededError, TypeNotAllowedError
from app.shared.base_error import NotFoundError
from app.shared.contracts.emis import EmisCertificate
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.ids import new_id

ALLOWED = (".png", ".jpg", ".jpeg", ".pdf", ".docx")


class FakeFiles:
    """FilesApi subset: type check, per-owner quota, content, deletion."""

    def __init__(self, quota: int = 1_000_000) -> None:
        """Start empty with a per-owner quota in bytes."""
        self.quota = quota
        self.files: dict[UUID, FileRef] = {}
        self.objects: dict[UUID, bytes] = {}
        self.deleted: list[UUID] = []

    def used(self, owner_id: UUID) -> int:
        """Bytes the owner's live files take."""
        return sum(
            f.byte_size
            for f in self.files.values()
            if f.owner_id == owner_id and f.id not in self.deleted
        )

    async def transfer_ownership(
        self, file_ids: Sequence[UUID], new_owner_id: UUID
    ) -> None:
        """Record the moves (the fake keeps no quota)."""
        self.transferred: list[tuple[UUID, UUID]] = [
            *getattr(self, "transferred", []),
            *((file_id, new_owner_id) for file_id in file_ids),
        ]

    async def store_bytes(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
        expires_days: int | None = None,
    ) -> FileRef:
        """Store a file like the real module: type and quota are checked."""
        if not name.lower().endswith(ALLOWED):
            raise TypeNotAllowedError()
        if self.used(owner_id) + len(data) > self.quota:
            raise QuotaExceededError()
        file = FileRef(
            id=new_id(),
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            content_type="application/octet-stream",
            byte_size=len(data),
            status="ready",
            text_bytes=None,
        )
        self.files[file.id] = file
        self.objects[file.id] = data
        return file

    async def read_bytes(self, file_id: UUID) -> bytes:
        """The stored content."""
        return self.objects[file_id]

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """A presigned-looking URL."""
        if file_id not in self.files or file_id in self.deleted:
            raise NotFoundError()
        return f"https://storage.test/{file_id}?sig=abc"

    async def delete_file(self, file_id: UUID) -> None:
        """Delete (repeatable)."""
        self.deleted.append(file_id)
        self.objects.pop(file_id, None)


@dataclass
class FakeDirectory:
    """StudentDirectory over a list of students; curators map to groups."""

    students_list: list[StudentInfo] = field(default_factory=list)
    curators: dict[UUID, list[UUID]] = field(default_factory=dict)

    async def student(self, user_id: UUID) -> StudentInfo | None:
        """The student with this id."""
        return next((s for s in self.students_list if s.id == user_id), None)

    async def students(
        self,
        group_ids: Sequence[UUID] | None,
        *,
        subgroup: str | None = None,
        query: str | None = None,
    ) -> list[StudentInfo]:
        """Students of the groups, filtered, by name."""
        words = (query or "").casefold().split()
        found = [
            s
            for s in self.students_list
            if (group_ids is None or s.group_id in group_ids)
            and (subgroup is None or s.subgroup == subgroup)
            and all(w in s.name.casefold() for w in words)
        ]
        return sorted(found, key=lambda s: s.name)

    async def groups(self, group_ids: Sequence[UUID] | None) -> list[GroupInfo]:
        """Groups with their subgroups."""
        names: dict[UUID, str] = {}
        subs: dict[UUID, set[str]] = {}
        for s in self.students_list:
            if group_ids is None or s.group_id in group_ids:
                names[s.group_id] = s.group_name
                subs.setdefault(s.group_id, set())
                if s.subgroup:
                    subs[s.group_id].add(s.subgroup)
        return [
            GroupInfo(gid, names[gid], tuple(sorted(subs[gid])))
            for gid in sorted(names, key=lambda g: names[g])
        ]

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """The teacher's groups."""
        return list(self.curators.get(teacher_id, []))


class FakeEmis:
    """EmisSource subset: ``certificates`` returns what the test set."""

    def __init__(self) -> None:
        """Start with no certificates."""
        self.items: list[EmisCertificate] = []
        self.error: Exception | None = None

    async def certificates(self, user_id: UUID) -> list[EmisCertificate]:
        """The configured certificates, or raise the configured error."""
        if self.error is not None:
            raise self.error
        return list(self.items)


class FakeFetcher:
    """CertificateFetcher: serves a PDF, or fails for URLs in ``broken``."""

    def __init__(self) -> None:
        """Start with no failures."""
        self.broken: set[str] = set()
        self.urls: list[str] = []

    async def fetch(self, url: str) -> FetchedFile:
        """Return a small PDF."""
        self.urls.append(url)
        if url in self.broken:
            raise CertificateDownloadError()
        return FetchedFile(name=url.rsplit("/", 1)[-1], data=b"%PDF-1.4 fake")
