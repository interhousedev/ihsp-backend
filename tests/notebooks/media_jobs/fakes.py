"""In-memory fakes of the media ports (spec 3.3/3.4), shared by the media tests."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class WordTiming:
    """Word boundary from a provider (ms)."""

    word: str
    start_ms: int
    end_ms: int


class FakeSpeechSynthesizer:
    """`SpeechSynthesizer`: 10 ms per character, deterministic bytes, word timings."""

    def __init__(self, *, with_timings: bool = True) -> None:
        self.calls: list[tuple[str, str, str, float]] = []
        self.with_timings = with_timings
        self.fail_on: str | None = None
        self.on_call = None  # optional hook run at the start of every call

    async def synthesize(
        self, *, text: str, language: str, voice_id: str, speed: float = 1.0
    ) -> Any:
        from app.shared.contracts.speech import SynthesisResult

        self.calls.append((text, language, voice_id, speed))
        if self.on_call is not None:
            self.on_call()
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("tts down")
        duration = int(len(text) * 10 / speed)
        words, cursor = [], 0
        for word in text.split():
            step = duration * len(word) // max(len(text), 1)
            words.append(WordTiming(word, cursor, cursor + step))
            cursor += step
        return SynthesisResult(
            audio=f"audio:{text}".encode(),
            duration_ms=duration,
            word_timings=tuple(words) if self.with_timings else (),
            chars_billed=len(text),
        )


@dataclass
class FakeFiles:
    """`MediaFiles`: stores bytes under new ids, private by default."""

    blobs: dict[UUID, tuple[str, bytes, str]] = field(default_factory=dict)

    async def put(
        self, *, owner_id: UUID, name: str, content: bytes, mime: str
    ) -> UUID:
        file_id = new_id()
        self.blobs[file_id] = (name, content, mime)
        return file_id


class FakeRenderer:
    """`VideoRenderer`: returns fixed MP4 bytes; can fail N times first.

    `segments` are the aligned script segments: the renderer builds the HyperFrames
    composition (one vetted scene template per segment) from them, so the same input is
    the same video; `audio` is the narration track it muxes in. A real implementation
    is also covered by a decodable-media integration test (ffprobe on the output).
    """

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0
        self.last_audio: bytes | None = None
        self.last_segments: tuple = ()

    async def render(
        self,
        *,
        composition_hash: str,
        fmt: str,
        length_s: int,
        segments: tuple,
        audio: bytes | None = None,
    ) -> bytes:
        self.calls += 1
        self.last_audio = audio
        self.last_segments = segments
        if self.failures:
            self.failures -= 1
            raise RuntimeError("chromium crashed")
        return b"mp4:" + composition_hash.encode()


class FakeMediaJobStore:
    """`MediaJobStore` over a dict."""

    def __init__(self) -> None:
        self.jobs: dict[UUID, object] = {}

    async def add(self, job: Any) -> None:
        self.jobs[job.id] = job

    async def get(self, job_id: UUID) -> Any:
        return self.jobs.get(job_id)

    async def save(self, job: Any) -> None:
        self.jobs[job.id] = job

    async def list_by_owner(self, owner_id: Any, *, limit: int, offset: int) -> Any:
        mine = sorted(
            (j for j in self.jobs.values() if j.owner_id == owner_id),
            key=lambda j: j.created_at,
            reverse=True,
        )
        return mine[offset : offset + limit], len(mine)

    async def find_done(self, owner_id: UUID, script_hash: str) -> list[Any]:
        """DONE jobs of the owner with this content hash (any destination)."""
        return [
            j
            for j in self.jobs.values()
            if j.owner_id == owner_id
            and j.script_hash == script_hash
            and j.status.name == "DONE"
        ]


class FakeNotebookSink:
    """`MaterialSink`: records what a finished job stores in the subject notebook."""

    def __init__(self) -> None:
        self.stored: list[object] = []
        self.failures = 0

    async def store(self, actor: Actor, material: Any) -> Any:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("notebook down")
        self.stored.append(material)


class FakeAccess:
    """`OwnerAccess`: the owner as an `Actor` if they may still use the destination.

    Revalidated by the worker right before any paid step; None = role or assignment
    was revoked since enqueue.
    """

    def __init__(self) -> None:
        self.revoked = False

    async def actor_for(self, owner_id: Any, subject_id: Any, group_id: Any) -> Any:
        from app.shared.actor import Role
        from tests.factories import make_actor

        if self.revoked:
            return None
        return make_actor(Role.TEACHER, user_id=owner_id)
