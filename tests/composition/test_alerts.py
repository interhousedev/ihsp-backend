"""WEB-3: alerts on the student's Today page (GET /v1/me/alerts)."""

import datetime as dt
from dataclasses import replace

from app.shared.actor import Role
from app.shared.ids import new_id
from tests.composition.conftest import ClientFor, World, actor_of
from tests.composition.fakes import make_lesson

ALERT_KINDS = [
    "emis_reauth",
    "no_subgroup",
    "files_expiring",
    "pending_approvals",
    "sync_failed",
]


async def test_a_student_with_nothing_to_fix_gets_no_alerts(world: World) -> None:
    """WEB-3: the Alerts card is shown only when relevant."""
    student = world.add_student()

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == []


async def test_emis_reauth_points_to_the_emis_page_of_the_id_app(
    world: World,
) -> None:
    """WEB-3: the EMIS password needs updating."""
    student = world.add_student(emis_status="needs_reauth")

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == [
        {
            "kind": "emis_reauth",
            "params": {},
            "action_url": f"{world.settings.urls.id}/security/emis/",
        }
    ]


async def test_no_subgroup_names_the_group_and_points_to_the_profile(
    world: World,
) -> None:
    """WEB-3: subgroup not set."""
    student = world.add_student(subgroup=None)

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == [
        {
            "kind": "no_subgroup",
            "params": {"group_name": "2TN2"},
            "action_url": f"{world.settings.urls.sp}/profile/",
        }
    ]


async def test_files_expiring_counts_the_files_due_within_a_week(
    world: World,
) -> None:
    """WEB-3, FILE-5: files will be deleted at the end of the term."""
    student = world.add_student()
    world.files.expiring = [dt.date(2026, 10, 9), dt.date(2026, 10, 13)]

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert world.files.until_calls == [dt.date(2026, 10, 13)]
    assert alerts == [
        {
            "kind": "files_expiring",
            "params": {"count": 2, "expires_on": "2026-10-09"},
            "action_url": f"{world.settings.urls.sp}/files/",
        }
    ]


async def test_files_that_expire_later_raise_no_alert(world: World) -> None:
    """WEB-3: a month away is not worth a card."""
    student = world.add_student()
    world.files.expiring = [dt.date(2026, 11, 20)]

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == []


async def test_pending_approvals_counts_the_waiting_assistant_actions(
    world: World,
) -> None:
    """WEB-3, AI-2: assistant actions waiting for approval."""
    student = world.add_student()
    world.ai.pending[student.id] = 2

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == [
        {
            "kind": "pending_approvals",
            "params": {"count": 2},
            "action_url": f"{world.settings.urls.sp}/assistant/",
        }
    ]


async def test_sync_failed_reports_the_number_of_failures(world: World) -> None:
    """SYNC: the last syncs of this student failed."""
    student = world.add_student()
    world.sync.failures[student.id] = 3

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == [
        {
            "kind": "sync_failed",
            "params": {"failures": 3},
            "action_url": f"{world.settings.urls.sp}/profile/",
        }
    ]


async def test_alerts_come_in_a_stable_order(world: World) -> None:
    """WEB-3: most important first."""
    student = world.add_student(subgroup=None, emis_status="needs_reauth")
    world.files.expiring = [dt.date(2026, 10, 8)]
    world.ai.pending[student.id] = 1
    world.sync.failures[student.id] = 1

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert [alert["kind"] for alert in alerts] == ALERT_KINDS


async def test_a_student_who_left_is_not_asked_for_a_subgroup(world: World) -> None:
    """WEB-3: nothing to fix for a former student."""
    student = world.add_student(subgroup=None)
    record = world.schedule.students[student.id]
    world.schedule.students[student.id] = replace(record, status="left")

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == []


async def test_endpoint_returns_alert_objects(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/me/alerts: Alert[] with kind, params and action_url."""
    student = world.add_student(emis_status="needs_reauth")
    client = await client_for(actor_of(student))

    response = await client.get("/v1/me/alerts")

    assert response.status_code == 200
    assert response.json() == [
        {
            "kind": "emis_reauth",
            "params": {},
            "action_url": f"{world.settings.urls.id}/security/emis/",
        }
    ]


async def test_a_teacher_cannot_read_student_alerts(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/me/alerts is for students."""
    teacher = world.add_user(Role.TEACHER)
    client = await client_for(actor_of(teacher))

    response = await client.get("/v1/me/alerts")

    assert response.status_code == 403
    assert response.json()["type"] == "common/forbidden"


async def test_alerts_need_a_login(client_for: ClientFor) -> None:
    """GET /v1/me/alerts without a token answers 401."""
    client = await client_for(None)

    response = await client.get("/v1/me/alerts")

    assert response.status_code == 401


async def test_a_seminar_starting_soon_is_alerted_and_a_lecture_is_not(
    world: World,
) -> None:
    """Alerts: a practice lesson (seminar) starting within 3 hours is alerted."""
    student = world.add_student()
    now = world.clock.now()
    day = now.date()
    seminar = replace(
        make_lesson(day=day, period=1, subject="Algebra"),
        starts_at=now + dt.timedelta(hours=1),
        ends_at=now + dt.timedelta(hours=2),
        kind="practice",
    )
    lecture = replace(seminar, id=new_id(), kind="lecture")
    world.schedule.projected = [lecture, seminar]

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert [a for a in alerts if a["kind"] == "seminar_soon"] == [
        {
            "kind": "seminar_soon",
            "params": {
                "subject_name": "Algebra",
                "starts_at": (now + dt.timedelta(hours=1)).isoformat(),
                "period": 1,
            },
            "action_url": f"{world.settings.urls.sp}/schedule/",
        }
    ]


async def test_a_student_without_a_connected_ai_client_is_told_to_connect(
    world: World,
) -> None:
    """MCP-5: no active AI connector gives one `connect_ai` alert to the wizard."""
    student = world.add_student(connected_ai=False)

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert alerts == [
        {
            "kind": "connect_ai",
            "params": {},
            "action_url": f"{world.settings.urls.id}/connectors/new/",
        }
    ]


async def test_connect_ai_is_not_shown_once_a_client_is_connected(
    world: World,
) -> None:
    """MCP-5: the alert is gone after the first connected client."""
    student = world.add_student()

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert all(alert["kind"] != "connect_ai" for alert in alerts)


async def test_connect_ai_respects_revoked_chat_access(world: World) -> None:
    """AI-8: an Administration block on the chat AI is not solved by a client."""
    student = world.add_student(connected_ai=False)
    world.ai_clients.revoked.add(student.id)

    alerts = await world.composition.build_alerts.execute(actor_of(student))

    assert all(alert["kind"] != "connect_ai" for alert in alerts)


async def test_connect_ai_is_only_for_students(world: World) -> None:
    """MCP-5: a teacher is not offered the student's AI wizard alert."""
    teacher = world.add_user(Role.TEACHER)

    alerts = await world.composition.build_alerts.execute(actor_of(teacher))

    assert all(alert["kind"] != "connect_ai" for alert in alerts)
