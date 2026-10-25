"""Job tracker: queued, running, progress, cooperative stop, admin endpoints."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_jobs import ROUTERS
from app.shared import jobs
from app.shared.actor import Role
from app.shared.jobs import (
    JobCancelled,
    MemoryJobTracker,
    RedisJobTracker,
    enqueue,
    job_progress,
    job_should_stop,
    run_job,
)


async def test_a_job_runs_reports_progress_and_finishes() -> None:
    tracker = MemoryJobTracker()
    job_id = await enqueue(tracker, "k", "Label", started_by="admin")
    async with run_job(tracker, "k", "Label", job_id=job_id) as job:
        assert job is not None
        await job_progress(done=1, total=3, add={"files": 2})
        await job_progress(add={"files": 1})
    stored = await tracker.get(job_id)
    assert stored is not None
    assert (stored.status, stored.done, stored.total) == ("done", 1, 3)
    assert stored.counters == {"files": 3}
    assert stored.started_by == "admin"


async def test_cancel_drops_a_queued_job() -> None:
    tracker = MemoryJobTracker()
    job_id = await enqueue(tracker, "k", "L")
    cancelled = await jobs.cancel(tracker, job_id)
    assert cancelled is not None and cancelled.status == "cancelled"
    async with run_job(tracker, "k", "L", job_id=job_id) as job:
        assert job is None


async def test_the_cancel_flag_stops_the_loop(monkeypatch: Any) -> None:
    monkeypatch.setattr(jobs, "STOP_CHECK_SECONDS", 0.0)
    tracker = MemoryJobTracker()
    seen = []
    async with run_job(tracker, "k", "L", job_id="j1"):
        for step in range(10):
            if await job_should_stop():
                raise JobCancelled()
            seen.append(step)
            if step == 2:
                stopping = await jobs.cancel(tracker, "j1")
                assert stopping is not None and stopping.status == "stopping"
    assert seen == [0, 1, 2]
    stored = await tracker.get("j1")
    assert stored is not None and stored.status == "cancelled"


async def test_outside_a_job_the_helpers_do_nothing() -> None:
    assert await job_should_stop() is False
    await job_progress(done=1)


async def test_jobs_endpoints(http_client: Any, make_actor: Any, redis: Any) -> None:
    tracker = RedisJobTracker(redis)
    job_id = await enqueue(tracker, "academic.resync_materials", "EMIS 2026/1")
    admin = await http_client(ROUTERS, {get_actor: lambda: make_actor(Role.ADMIN)})

    listed = await admin.get("/v1/admin/jobs")
    assert listed.status_code == 200
    [item] = listed.json()["items"]
    assert (item["id"], item["status"]) == (job_id, "queued")

    stopped = await admin.post(f"/v1/admin/jobs/{job_id}/cancel")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "cancelled"
    assert await tracker.is_cancelled(job_id)
    assert (await admin.post("/v1/admin/jobs/nope/cancel")).status_code == 404


async def test_jobs_endpoints_are_for_admins(http_client: Any, make_actor: Any) -> None:
    teacher = await http_client(ROUTERS, {get_actor: lambda: make_actor(Role.TEACHER)})
    assert (await teacher.get("/v1/admin/jobs")).status_code == 403
    assert (await teacher.post("/v1/admin/jobs/x/cancel")).status_code == 403
