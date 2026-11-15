"""PUT /v1/admin/students/{id}/group: an administrator sets a student's group."""

import uuid

from app.shared.actor import Role
from tests.academic.schedule.conftest import Api
from tests.academic.schedule.env import Env


async def test_admin_moves_a_student_and_resets_the_subgroup(
    env: Env, api: Api
) -> None:
    """The group changes, the subgroup is cleared, the change is audited."""
    old = await env.group("2TN2")
    new = await env.group("2TN3")
    pupil = await env.student(old, subgroup=2)

    response = await api.client.put(
        f"/v1/admin/students/{pupil.id}/group", json={"group_id": str(new.id)}
    )

    assert response.status_code == 204
    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None
    assert student.group_id == new.id
    assert student.subgroup is None
    audit = next(a for a in env.audits if a.type == "student.group_changed")
    assert audit.metadata == {"from_group_id": str(old.id), "to_group_id": str(new.id)}


async def test_admin_can_detach_a_student(env: Env, api: Api) -> None:
    """null leaves the student without a group."""
    group = await env.group("2TN2")
    pupil = await env.student(group)

    response = await api.client.put(
        f"/v1/admin/students/{pupil.id}/group", json={"group_id": None}
    )

    assert response.status_code == 204
    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None and student.group_id is None


async def test_unknown_group_or_student_answers_404(env: Env, api: Api) -> None:
    """Both ids must exist."""
    group = await env.group("2TN2")
    pupil = await env.student(group)

    no_group = await api.client.put(
        f"/v1/admin/students/{pupil.id}/group", json={"group_id": str(uuid.uuid4())}
    )
    no_student = await api.client.put(
        f"/v1/admin/students/{uuid.uuid4()}/group", json={"group_id": str(group.id)}
    )

    assert no_group.status_code == 404
    assert no_group.json()["type"] == "academic/group-not-found"
    assert no_student.status_code == 404
    assert no_student.json()["type"] == "academic/student-not-found"


async def test_a_non_admin_cannot_set_a_student_group(env: Env, api: Api) -> None:
    """Only administrators."""
    group = await env.group("2TN2")
    pupil = await env.student(group)
    api.as_role(Role.TEACHER)

    response = await api.client.put(
        f"/v1/admin/students/{pupil.id}/group", json={"group_id": None}
    )

    assert response.status_code == 403
