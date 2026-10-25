"""HTTP: the subject reconcile is queued (202) and its totals are read from the job."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.http.v1.notebooks.reconcile_jobs import start_reconcile
from app.interfaces.jobs.context import set_container
from app.interfaces.jobs.tasks.notebooks.reconcile_subject_materials import (
    reconcile_subject_materials,
)
from app.modules.notebooks.application.reconcile_subject_materials import (
    RECONCILE_TASK,
    ReconcileResult,
)
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from app.shared.jobs import RedisJobTracker
from app.shared.tasks import TaskKickFailedError
from tests.fakes.tasks import FakeTaskKicker

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

SUBJECT = str(new_id())
ADMIN_BASE = f"/v1/admin/subject-materials/subjects/{SUBJECT}/reconcile"
STAFF_BASE = f"/v1/staff/subjects/{SUBJECT}/reconcile"


@pytest.fixture
def admin(make_actor: Callable[..., Actor]) -> Actor:
    """An administrator."""
    return make_actor(Role.ADMIN)


@pytest.fixture
def teacher(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher."""
    return make_actor(Role.TEACHER)


async def test_admin_check_is_queued_and_polled(
    api: AsyncClient,
    current: dict[str, Actor],
    admin: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """POST answers 202 at once with a job id; the worker gets the job to run."""
    current["actor"] = admin

    started = await api.post(ADMIN_BASE)
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    status = await api.get(f"{ADMIN_BASE}/{job_id}")

    assert started.status_code == 202, started.text
    assert started.json() == {"job_id": job_id, "status": "queued"}
    assert kicker.calls == [
        (RECONCILE_TASK, {"subject_id": SUBJECT, "owner_id": None, "job_id": job_id})
    ]
    assert status.status_code == 200
    assert status.json() == {
        "job_id": job_id,
        "status": "queued",
        "done": False,
        "notebooks": 0,
        "added": 0,
        "already_present": 0,
        "skipped": 0,
    }


async def test_a_student_cannot_start_or_read_the_check(
    api: AsyncClient, current: dict[str, Actor], admin: Actor
) -> None:
    """Only admins reach the admin route; a student gets 403 on both verbs."""
    current["actor"] = admin
    job_id = (await api.post(ADMIN_BASE)).json()["job_id"]
    current["actor"] = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))

    assert (await api.post(ADMIN_BASE)).status_code == 403
    assert (await api.get(f"{ADMIN_BASE}/{job_id}")).status_code == 403


async def test_a_teacher_checks_own_notebooks_and_reads_only_own_job(
    api: AsyncClient,
    current: dict[str, Actor],
    teacher: Actor,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> None:
    """The teacher's job names them as owner; another teacher gets 404 on it."""
    current["actor"] = teacher

    started = await api.post(STAFF_BASE)
    job_id = started.json()["job_id"]
    own = await api.get(f"{STAFF_BASE}/{job_id}")
    current["actor"] = make_actor(Role.TEACHER)
    other = await api.get(f"{STAFF_BASE}/{job_id}")

    assert started.status_code == 202, started.text
    assert kicker.calls[-1][1]["owner_id"] == str(teacher.user_id)
    assert own.status_code == 200
    assert other.status_code == 404


async def test_the_worker_run_sets_the_totals_on_the_job(
    api: AsyncClient,
    current: dict[str, Actor],
    admin: Actor,
    kicker: FakeTaskKicker,
    redis: Redis,
) -> None:
    """The queued task syncs the subject; the status then shows done and the counts."""
    current["actor"] = admin
    job_id = (await api.post(ADMIN_BASE)).json()["job_id"]
    _, kwargs = kicker.calls[-1]
    service = _FakeReconcile(ReconcileResult(notebooks=2, added=1, already_present=1))
    notebooks = SimpleNamespace(reconcile_subject_materials=service)
    container = SimpleNamespace(redis=redis, notebooks=notebooks)
    set_container(container)  # type: ignore[arg-type]

    checked = await reconcile_subject_materials(
        subject_id=kwargs["subject_id"], owner_id=None, job_id=job_id
    )
    status = await api.get(f"{ADMIN_BASE}/{job_id}")

    assert checked == 2
    assert service.subject_id == UUID(kwargs["subject_id"])
    assert status.json() == {
        "job_id": job_id,
        "status": "done",
        "done": True,
        "notebooks": 2,
        "added": 1,
        "already_present": 1,
        "skipped": 0,
    }


async def test_a_refused_kick_marks_the_job_failed(redis: Redis) -> None:
    """A refused task leaves the job failed, not queued forever."""

    class RefusingKicker(FakeTaskKicker):
        async def kick(self, task_name: str, **kwargs: Any) -> None:
            raise TaskKickFailedError(params={"task": task_name})

    container = SimpleNamespace(redis=redis, kicker=RefusingKicker())
    admin_id = new_id()

    with pytest.raises(TaskKickFailedError):
        await start_reconcile(
            container,  # type: ignore[arg-type]
            UUID(int=101),
            None,
            admin_id,
        )

    jobs = await RedisJobTracker(redis).list_all()
    assert [(job.kind, job.status) for job in jobs] == [(RECONCILE_TASK, "failed")]


class _FakeReconcile:
    """Stands in for the use case; records the subject it was asked to check."""

    def __init__(self, result: ReconcileResult) -> None:
        self.result = result
        self.subject_id: UUID | None = None

    async def execute(self, subject_id: UUID, owner_id: UUID | None = None) -> Any:
        self.subject_id = subject_id
        return self.result
