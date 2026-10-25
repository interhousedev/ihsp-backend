"""GET /v1/admin/jobs and POST /v1/admin/jobs/{job_id}/cancel."""

from dataclasses import asdict
from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role
from app.shared.jobs import ACTIVE, JobNotFoundError, RedisJobTracker, cancel

from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admin/jobs", tags=["admin-jobs"])


class JobResponse(BaseModel):
    """One worker job."""

    id: str
    kind: str
    label: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    started_by: str | None
    done: int
    total: int | None
    note: str | None
    counters: dict[str, int]


class JobListResponse(BaseModel):
    """Active jobs (queued, running, stopping) and those finished today."""

    items: list[JobResponse]


@router.get("", response_model=JobListResponse)
async def list_jobs(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> JobListResponse:
    """Active jobs first, then the recently finished ones (newest first)."""
    jobs = await RedisJobTracker(container.redis).list_all()
    jobs.sort(key=lambda job: job.status not in ACTIVE)
    return JobListResponse(items=[JobResponse(**asdict(job)) for job in jobs])


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> JobResponse:
    """Stop a job: a queued one is dropped, a running one stops at its next check."""
    job = await cancel(RedisJobTracker(container.redis), job_id)
    if job is None:
        raise JobNotFoundError(params={"job_id": job_id})
    return JobResponse(**asdict(job))
