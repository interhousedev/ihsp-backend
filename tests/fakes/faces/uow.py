"""In-memory faces storage, unit of work, directory, excuses, files and sniffer."""

from collections.abc import Sequence
from datetime import date, datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.faces.domain.models import Device, DeviceCall, FaceProfile, Passage
from app.modules.faces.ports.directory import StudentInfo
from app.shared.contracts.excuses import ExcuseStatus
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft


class FakeFacesStore:
    """All rows of the module plus the notifications committed."""

    def __init__(self) -> None:
        """Start empty."""
        self.profiles: dict[UUID, FaceProfile] = {}
        self.devices: dict[UUID, Device] = {}
        self.calls: list[DeviceCall] = []
        self.passages: list[Passage] = []
        self.notifications: list[NotificationDraft] = []


class _Profiles:
    def __init__(self, store: FakeFacesStore) -> None:
        self._s = store

    async def get(self, user_id: UUID) -> FaceProfile | None:
        return self._s.profiles.get(user_id)

    async def save(self, profile: FaceProfile) -> None:
        self._s.profiles[profile.user_id] = profile

    async def delete(self, user_id: UUID) -> None:
        self._s.profiles.pop(user_id, None)

    async def embeddings(self) -> list[tuple[UUID, list[float]]]:
        return [(u, p.embedding) for u, p in self._s.profiles.items()]


class _Devices:
    def __init__(self, store: FakeFacesStore) -> None:
        self._s = store

    async def add(self, device: Device) -> None:
        self._s.devices[device.id] = device

    async def get(self, device_id: UUID) -> Device | None:
        return self._s.devices.get(device_id)

    async def by_hash(self, key_hash: str) -> Device | None:
        for device in self._s.devices.values():
            if device.key_hash == key_hash:
                return device
        return None

    async def list_all(self) -> list[Device]:
        return sorted(
            self._s.devices.values(), key=lambda d: d.created_at, reverse=True
        )

    async def revoke(self, device_id: UUID, at: datetime) -> None:
        self._s.devices[device_id].revoked_at = at

    async def touch(self, device_id: UUID, at: datetime) -> None:
        self._s.devices[device_id].last_used_at = at


class _Activity:
    def __init__(self, store: FakeFacesStore) -> None:
        self._s = store

    async def add_call(self, call: DeviceCall) -> None:
        self._s.calls.append(call)

    async def add_passage(self, passage: Passage) -> None:
        self._s.passages.append(passage)

    async def calls(self, device_id: UUID, since: datetime) -> list[DeviceCall]:
        found = [c for c in self._s.calls if c.device_id == device_id and c.at >= since]
        return sorted(found, key=lambda c: c.at, reverse=True)

    async def purge_before(self, cutoff: datetime) -> int:
        calls = [c for c in self._s.calls if c.at >= cutoff]
        passages = [p for p in self._s.passages if p.at >= cutoff]
        removed = (
            len(self._s.calls) - len(calls) + len(self._s.passages) - len(passages)
        )
        self._s.calls, self._s.passages = calls, passages
        return removed


class FakeFacesUow:
    """Applies changes at once; notifications land only on commit."""

    def __init__(self, store: FakeFacesStore) -> None:
        """Bind the store."""
        self._store = store
        self._pending: list[NotificationDraft] = []
        self.profiles = _Profiles(store)
        self.devices = _Devices(store)
        self.activity = _Activity(store)

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._pending.extend(drafts)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Drop uncommitted notifications."""
        self._pending = []

    async def commit(self) -> None:
        """Publish the queued notifications."""
        self._store.notifications.extend(self._pending)
        self._pending = []


class FakeDirectory:
    """Students, curators and names in dicts."""

    def __init__(self) -> None:
        """Nobody yet."""
        self.students: dict[UUID, StudentInfo] = {}
        self.curators: set[tuple[UUID, UUID]] = set()

    def add_student(self, name: str, group: str = "2TN2") -> StudentInfo:
        """Register a student in a fresh group."""
        info = StudentInfo(new_id(), name, new_id(), group)
        self.students[info.user_id] = info
        return info

    async def student(self, user_id: UUID) -> StudentInfo | None:
        """Return the student."""
        return self.students.get(user_id)

    async def curates(self, teacher_id: UUID, group_id: UUID) -> bool:
        """Return whether the teacher curates the group."""
        return (teacher_id, group_id) in self.curators

    async def full_names(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return known names."""
        return {i: s.full_name for i, s in self.students.items() if i in user_ids}


class FakeExcuses:
    """Excuse state set by the test."""

    def __init__(self) -> None:
        """Nobody excused, no lesson."""
        self.excused = False
        self.in_lesson = False
        self.until: date | None = None
        self.curator_id: UUID | None = None

    async def status(self, student_id: UUID, at: datetime) -> ExcuseStatus:
        """Return the configured state."""
        return ExcuseStatus(
            student_id=student_id,
            excused_now=self.excused,
            excuse_id=new_id() if self.excused else None,
            until=self.until,
            in_lesson_time=self.in_lesson,
            curator_id=self.curator_id,
            group_id=None,
        )


class FakeFaceFiles:
    """The part of FilesApi the module uses."""

    def __init__(self) -> None:
        """No files yet."""
        self.files: dict[UUID, FileRef] = {}

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
        """Keep the file."""
        ref = FileRef(
            new_id(), owner_id, scope, purpose, name, "image/png", len(data),
            "ready", None,
        )  # fmt: skip
        self.files[ref.id] = ref
        return ref

    async def delete_file(self, file_id: UUID) -> None:
        """Forget the file."""
        self.files.pop(file_id, None)

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """A fake URL."""
        return f"https://s3.test/{file_id}"


class FakeSniffer:
    """Recognises PNG and JPEG by magic bytes."""

    async def sniff(self, head: bytes) -> str:
        """Return the MIME type."""
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        return "application/octet-stream"
