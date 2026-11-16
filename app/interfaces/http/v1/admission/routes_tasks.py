"""Tasks: a student's to-do board with steps and links, and AI suggestions.

The student is the assignee. Staff with the right permission create and edit tasks
for a student in scope; the student keeps full control of their own board.
`POST /tasks/suggest` returns drafts that are not stored; the student accepts the
ones they want with `POST /tasks/suggest/accept`.
"""

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.domain.tasks import (
    DESCRIPTION_MAX,
    LABEL_MAX,
    LINKS_MAX,
    STEP_MAX,
    STEPS_MAX,
    SUGGEST_MAX,
    TITLE_MAX,
    URL_MAX,
    Task,
    TaskLink,
    TaskStep,
)
from app.shared.ids import new_id

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Status = Literal["planned", "in_progress", "in_review", "blocked", "done"]
Priority = Literal["low", "medium", "high"]
Source = Literal["student", "mentor", "counselor", "ai"]
Horizon = Literal["overdue", "week", "month"]
Kind = Literal["external", "internal"]
Lang = Annotated[str | None, Header(alias="Accept-Language")]


class LinkIO(BaseModel):
    """A labelled link: an outside page (`external`) or a route (`internal`)."""

    label: str = Field(min_length=1, max_length=LABEL_MAX)
    url: str = Field(min_length=1, max_length=URL_MAX)
    kind: Kind


class StepOut(BaseModel):
    """One checklist step."""

    id: UUID
    title: str
    done: bool
    link: LinkIO | None


class StepIn(BaseModel):
    """A step to store; keep `id` to preserve a step's identity and state."""

    id: UUID | None = None
    title: str = Field(min_length=1, max_length=STEP_MAX)
    done: bool = False
    link: LinkIO | None = None


class ProgressOut(BaseModel):
    """Done and total steps."""

    done: int
    total: int


class TaskOut(BaseModel):
    """A task. `overdue` is computed against today in Tashkent."""

    id: UUID
    student_id: UUID
    title: str
    description: str
    status: Status
    priority: Priority
    start_date: dt.date | None
    deadline: dt.date | None
    created_by: Source
    creator_id: UUID | None
    steps: list[StepOut]
    links: list[LinkIO]
    progress: ProgressOut
    overdue: bool
    completed_at: dt.datetime | None
    lock_version: int
    created_at: dt.datetime | None
    updated_at: dt.datetime | None


class TasksOut(BaseModel):
    """A list of tasks."""

    items: list[TaskOut]


class TaskIn(BaseModel):
    """A task to create."""

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    priority: Priority = "medium"
    start_date: dt.date | None = None
    deadline: dt.date | None = None
    steps: list[StepIn] = Field(default_factory=list, max_length=STEPS_MAX)
    links: list[LinkIO] = Field(default_factory=list, max_length=LINKS_MAX)


_NOT_NULL = ("title", "description", "priority", "status")


class TaskPatch(BaseModel):
    """Fields to change; omitted ones stay. `lock_version` guards against races."""

    lock_version: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    status: Status | None = None
    priority: Priority | None = None
    start_date: dt.date | None = None
    deadline: dt.date | None = None
    steps: list[StepIn] | None = Field(default=None, max_length=STEPS_MAX)
    links: list[LinkIO] | None = Field(default=None, max_length=LINKS_MAX)


class StepPatch(BaseModel):
    """Check or uncheck a step."""

    done: bool


class AcceptIn(BaseModel):
    """Suggested tasks the student keeps."""

    tasks: list[TaskIn] = Field(min_length=1, max_length=SUGGEST_MAX)


def _link(x: LinkIO) -> TaskLink:
    return TaskLink(x.label, x.url, x.kind)


def _steps(items: list[StepIn]) -> tuple[TaskStep, ...]:
    return tuple(
        TaskStep(s.id or new_id(), s.title, s.done, _link(s.link) if s.link else None)
        for s in items
    )


def _draft(body: TaskIn) -> Task:
    return Task(
        id=new_id(),
        student_id=new_id(),
        title=body.title,
        description=body.description,
        priority=body.priority,
        start_date=body.start_date,
        deadline=body.deadline,
        steps=_steps(body.steps),
        links=tuple(_link(x) for x in body.links),
    )


def _out(t: Task, today: dt.date) -> TaskOut:
    done, total = t.progress
    link = LinkIO
    return TaskOut(
        id=t.id,
        student_id=t.student_id,
        title=t.title,
        description=t.description,
        status=t.status,
        priority=t.priority,
        start_date=t.start_date,
        deadline=t.deadline,
        created_by=t.created_by,
        creator_id=t.creator_id,
        steps=[
            StepOut(
                id=s.id,
                title=s.title,
                done=s.done,
                link=(
                    link(label=s.link.label, url=s.link.url, kind=s.link.kind)
                    if s.link
                    else None
                ),
            )
            for s in t.steps
        ],
        links=[link(label=x.label, url=x.url, kind=x.kind) for x in t.links],
        progress=ProgressOut(done=done, total=total),
        overdue=t.is_overdue(today),
        completed_at=t.completed_at,
        lock_version=t.lock_version,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def list_mine(
    container: ContainerDep,
    ctx: AdmissionCtx,
    status: Annotated[Status | None, Query()] = None,
    priority: Annotated[Priority | None, Query()] = None,
    source: Annotated[Source | None, Query()] = None,
    horizon: Annotated[Horizon | None, Query()] = None,
) -> TasksOut:
    """My tasks, newest deadline first; narrow by status, priority, source, time."""
    return await _list(container, ctx, ctx.user_id, status, priority, source, horizon)


async def list_student(
    student_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    status: Annotated[Status | None, Query()] = None,
    priority: Annotated[Priority | None, Query()] = None,
    source: Annotated[Source | None, Query()] = None,
    horizon: Annotated[Horizon | None, Query()] = None,
) -> TasksOut:
    """A student's tasks (staff in scope)."""
    return await _list(container, ctx, student_id, status, priority, source, horizon)


async def _list(
    container: ContainerDep,
    ctx: Any,
    student_id: UUID,
    status: str | None,
    priority: str | None,
    source: str | None,
    horizon: str | None,
) -> TasksOut:
    svc = container.admission.tasks
    rows = await svc.list_for(
        ctx,
        student_id,
        status=status,
        priority=priority,
        source=source,
        horizon=horizon,
    )
    today = svc.today()
    return TasksOut(items=[_out(t, today) for t in rows])


async def create_mine(
    body: TaskIn, container: ContainerDep, ctx: AdmissionCtx
) -> TaskOut:
    """Create a task on my own board."""
    return await create_for(ctx.user_id, body, container, ctx)


async def create_for(
    student_id: UUID, body: TaskIn, container: ContainerDep, ctx: AdmissionCtx
) -> TaskOut:
    """Create a task for a student (mentor or counselor in scope, or the owner)."""
    svc = container.admission.tasks
    task = await svc.create(ctx, student_id, _draft(body))
    return _out(task, svc.today())


async def get_task(
    task_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> TaskOut:
    """One task the caller may read."""
    svc = container.admission.tasks
    return _out(await svc.get(ctx, task_id), svc.today())


def patch_changes(body: TaskPatch) -> dict[str, Any]:
    """The fields to change; null on a required field means "unchanged"."""
    changes: dict[str, Any] = body.model_dump(
        exclude_unset=True, exclude={"lock_version", "steps", "links"}
    )
    for key in _NOT_NULL:
        if changes.get(key, 0) is None:
            del changes[key]
    if body.steps is not None:
        changes["steps"] = _steps(body.steps)
    if body.links is not None:
        changes["links"] = tuple(_link(x) for x in body.links)
    return changes


async def patch_task(
    task_id: UUID, body: TaskPatch, container: ContainerDep, ctx: AdmissionCtx
) -> TaskOut:
    """Change a task; a stale `lock_version` answers 409."""
    changes = patch_changes(body)
    svc = container.admission.tasks
    task = await svc.update(ctx, task_id, changes, body.lock_version)
    return _out(task, svc.today())


async def delete_task(
    task_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Delete a task."""
    await container.admission.tasks.delete(ctx, task_id)
    return Response(status_code=204)


async def patch_step(
    task_id: UUID,
    step_id: UUID,
    body: StepPatch,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> TaskOut:
    """Check or uncheck a step; the task status stays as it is."""
    svc = container.admission.tasks
    task = await svc.toggle_step(ctx, task_id, step_id, body.done)
    return _out(task, svc.today())


async def suggest(
    container: ContainerDep, ctx: AdmissionCtx, accept_language: Lang = None
) -> TasksOut:
    """AI task drafts for my board; nothing is stored (needs `admission_ai`)."""
    rows = await container.admission.tasks_ai.suggest(ctx, _locale(accept_language))
    today = container.admission.tasks.today()
    return TasksOut(items=[_out(t, today) for t in rows])


async def accept(
    body: AcceptIn, container: ContainerDep, ctx: AdmissionCtx
) -> TasksOut:
    """Store the suggested tasks I picked, as source `ai`."""
    svc = container.admission.tasks
    rows = await svc.create_many(ctx, [_draft(t) for t in body.tasks], source="ai")
    today = svc.today()
    return TasksOut(items=[_out(t, today) for t in rows])


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_route("/tasks", list_mine, "GET", "tasks_list", response_model=TasksOut)
_route("/tasks", create_mine, "POST", "tasks_create", response_model=TaskOut)
_route("/tasks/suggest", suggest, "POST", "tasks_suggest", response_model=TasksOut)
_route("/tasks/suggest/accept", accept, "POST", "tasks_accept", response_model=TasksOut)
_route("/tasks/{task_id}", get_task, "GET", "tasks_get", response_model=TaskOut)
_route("/tasks/{task_id}", patch_task, "PATCH", "tasks_update", response_model=TaskOut)
_route("/tasks/{task_id}", delete_task, "DELETE", "tasks_delete", status_code=204)
_route(
    "/tasks/{task_id}/steps/{step_id}",
    patch_step,
    "PATCH",
    "tasks_step",
    response_model=TaskOut,
)
_route(
    "/students/{student_id}/tasks",
    list_student,
    "GET",
    "tasks_for_student",
    response_model=TasksOut,
)
_route(
    "/students/{student_id}/tasks",
    create_for,
    "POST",
    "tasks_create_for_student",
    response_model=TaskOut,
)
