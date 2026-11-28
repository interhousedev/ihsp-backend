"""One media job: voice-over and video are stages of the same job."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.media.domain.narration import NarrationOptions, Segment
from app.shared.base_error import ConflictError
from app.shared.ids import new_id


class InvalidMediaTransitionError(ConflictError):
    """The job cannot make this move from its current status."""

    code = "media/invalid-transition"
    message_key = "media-invalid-transition"


class MediaKind(StrEnum):
    """What the teacher gets."""

    VIDEO_WITH_VOICE = "video_with_voice"
    AUDIO_ONLY = "audio_only"


class MediaStatus(StrEnum):
    """Where the job is."""

    QUEUED = "queued"
    VOICING = "voicing"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"


_ACTIVE = (MediaStatus.VOICING, MediaStatus.RENDERING)


@dataclass(slots=True)
class MediaJob:
    """A voiced script, optionally rendered to video, delivered to a notebook."""

    id: UUID
    owner_id: UUID
    kind: MediaKind
    script: tuple[Segment, ...]
    options: NarrationOptions
    subject_id: UUID
    group_id: UUID | None
    created_at: datetime
    status: MediaStatus = MediaStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    audio_file_id: UUID | None = None
    captions_file_id: UUID | None = None
    file_id: UUID | None = None
    storage_key: str | None = None
    segments: tuple[Segment, ...] = ()
    duration_ms: int = 0
    error: str | None = None
    delivered: bool = False
    version: int = field(default=0)

    @classmethod
    def queue(
        cls,
        owner_id: UUID,
        kind: MediaKind,
        script: tuple[Segment, ...],
        options: NarrationOptions,
        now: datetime,
        *,
        subject_id: UUID,
        group_id: UUID | None = None,
    ) -> "MediaJob":
        """A new queued job."""
        return cls(
            id=new_id(),
            owner_id=owner_id,
            kind=kind,
            script=tuple(script),
            options=options,
            subject_id=subject_id,
            group_id=group_id,
            created_at=now,
        )

    @property
    def script_hash(self) -> str:
        """Stable over the voiced content: text, voice, speed, language, kind."""
        payload = json.dumps(
            [
                self.kind.value,
                self.options.voice_id,
                self.options.speed,
                self.options.language,
                [[s.speaker, s.text] for s in self.script],
            ],
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def deliverables(self) -> tuple[str, ...]:
        """The only files a user downloads."""
        return ("mp4",) if self.kind is MediaKind.VIDEO_WITH_VOICE else ("mp3",)

    @staticmethod
    def storage_key_for(owner_id: UUID, script_hash: str, kind: MediaKind) -> str:
        """Deterministic, owner-scoped key of the result."""
        ext = "mp4" if kind is MediaKind.VIDEO_WITH_VOICE else "mp3"
        return f"media/jobs/{owner_id}/{script_hash}.{ext}"

    def _require(self, *allowed: MediaStatus) -> None:
        if self.status not in allowed:
            raise InvalidMediaTransitionError(
                params={"status": self.status.value},
                support_details=f"media job is {self.status.value}",
            )

    def start(self) -> None:
        """QUEUED -> VOICING."""
        self._require(MediaStatus.QUEUED)
        self.status = MediaStatus.VOICING
        self.attempts += 1

    def voiced(
        self,
        audio_file_id: UUID,
        captions_file_id: UUID,
        segments: tuple[Segment, ...],
        duration_ms: int,
    ) -> None:
        """VOICING -> RENDERING (video) or DONE (audio)."""
        self._require(MediaStatus.VOICING)
        self.audio_file_id = audio_file_id
        self.captions_file_id = captions_file_id
        self.segments = tuple(segments)
        self.duration_ms = duration_ms
        if self.kind is MediaKind.VIDEO_WITH_VOICE:
            self.status = MediaStatus.RENDERING
            return
        self.file_id = audio_file_id
        self.storage_key = self.storage_key_for(
            self.owner_id, self.script_hash, self.kind
        )
        self.error = None
        self.status = MediaStatus.DONE

    def complete(self, file_id: UUID, storage_key: str) -> None:
        """RENDERING -> DONE."""
        self._require(MediaStatus.RENDERING)
        self.file_id = file_id
        self.storage_key = storage_key
        self.error = None
        self.status = MediaStatus.DONE

    def fail(self, reason: str) -> None:
        """Requeue while attempts remain, else FAILED."""
        self._require(*_ACTIVE)
        self.error = reason
        self.status = (
            MediaStatus.QUEUED
            if self.attempts < self.max_attempts
            else MediaStatus.FAILED
        )

    def recover(self) -> None:
        """A stage left by a crashed worker: requeue or give up."""
        self._require(*_ACTIVE)
        if self.attempts < self.max_attempts:
            self.status = MediaStatus.QUEUED
        else:
            self.error = "worker lost"
            self.status = MediaStatus.FAILED

    def cancel(self) -> None:
        """Stop a job that has not finished."""
        self._require(MediaStatus.QUEUED, *_ACTIVE)
        self.error = "cancelled"
        self.status = MediaStatus.FAILED

    def retry(self) -> None:
        """FAILED -> QUEUED with a fresh set of attempts."""
        self._require(MediaStatus.FAILED)
        self.attempts = 0
        self.error = None
        self.status = MediaStatus.QUEUED

    def mark_delivered(self) -> None:
        """The notebook accepted the material."""
        self._require(MediaStatus.DONE)
        self.delivered = True
