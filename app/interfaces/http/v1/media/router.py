"""Start and follow a voice-over or video job."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.media.domain.media_job import MediaJob, MediaKind, MediaStatus
from app.modules.media.domain.narration import NarrationOptions, Segment
from app.shared.actor import Actor

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/media", tags=["media"])


class SegmentBody(BaseModel):
    """One spoken piece of the script."""

    id: str = Field(min_length=1, max_length=64)
    speaker: str = Field(default="host", max_length=64)
    text: str = Field(min_length=1, max_length=5000)
    source_refs: list[str] = Field(default_factory=list, max_length=20)


class MediaJobBody(BaseModel):
    """What to voice and where the result goes."""

    kind: MediaKind = MediaKind.VIDEO_WITH_VOICE
    script: list[SegmentBody] = Field(min_length=1, max_length=200)
    subject_id: UUID
    group_id: UUID | None = None
    style: str = Field(default="explainer", max_length=50)
    length: str = Field(default="medium", max_length=20)
    language: str = Field(default="ru", max_length=8)
    voice_id: str = Field(default="default", max_length=64)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class MediaJobView(BaseModel):
    """A job as the teacher sees it: status and the file to download."""

    id: UUID
    kind: MediaKind
    status: MediaStatus
    subject_id: UUID
    group_id: UUID | None
    file_id: UUID | None
    error: str | None

    @classmethod
    def of(cls, job: MediaJob) -> "MediaJobView":
        """Project a job."""
        return cls(
            id=job.id,
            kind=job.kind,
            status=job.status,
            subject_id=job.subject_id,
            group_id=job.group_id,
            file_id=job.file_id,
            error=job.error,
        )


class MediaJobPage(BaseModel):
    """One page of the caller's jobs."""

    items: list[MediaJobView]
    total: int


@router.get("/jobs")
async def list_jobs(
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MediaJobPage:
    """My jobs, newest first."""
    jobs, total = await container.media.list.execute(actor, limit=limit, offset=offset)
    return MediaJobPage(items=[MediaJobView.of(j) for j in jobs], total=total)


@router.post("/jobs", status_code=202)
async def create_job(
    body: MediaJobBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> MediaJobView:
    """Queue a job; the result lands in the subject notebook with its timecodes."""
    script = tuple(
        Segment(
            id=s.id, speaker=s.speaker, text=s.text, source_refs=tuple(s.source_refs)
        )
        for s in body.script
    )
    options = NarrationOptions(
        style=body.style,
        length=body.length,
        language=body.language,
        voice_id=body.voice_id,
        speed=body.speed,
    )
    job = await container.media.enqueue.execute(
        actor,
        body.kind,
        script,
        options,
        subject_id=body.subject_id,
        group_id=body.group_id,
    )
    return MediaJobView.of(job)


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> MediaJobView:
    """One job of the caller."""
    return MediaJobView.of(await container.media.get.execute(actor, job_id))


@router.post("/jobs/{job_id}:cancel")
async def cancel_job(
    job_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> MediaJobView:
    """Stop a job that has not finished; nothing is stored or charged afterwards."""
    return MediaJobView.of(await container.media.cancel.execute(actor, job_id))


@router.post("/jobs/{job_id}:retry", status_code=202)
async def retry_job(
    job_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> MediaJobView:
    """Start a failed job again."""
    return MediaJobView.of(await container.media.retry.execute(actor, job_id))
