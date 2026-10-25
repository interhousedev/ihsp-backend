"""The mark planner of one subject: GET /v1/me/subjects/{id}/planner (ACA-15)."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_marks import ROUTERS as MARKS_ROUTERS
from app.modules.academic.domain.marks.planner import parse_what_if
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Role
from tests.academic.marks.conftest import Env


async def _get(
    http_client: Any,
    services: MarksServices,
    actor: Any,
    subject_id: Any,
    params: Any = None,
) -> Any:
    client = await http_client(
        MARKS_ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(marks=services),
    )
    return await client.get(f"/v1/me/subjects/{subject_id}/planner", params=params)


async def test_planner_of_math_with_lesson_marks_and_a_midterm(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """Lesson 5, 4, 3 (4.00), midterm 5; second midterm and final still to come."""
    actor = make_actor(Role.STUDENT, user_id=env.world.user_id)

    response = await _get(http_client, services, actor, env.world.math_id)

    assert response.status_code == 200
    body = response.json()
    assert body["subject"]["short_name"] == "Math"
    assert body["semester"] == 3
    assert body["lesson"] == {"count": 3, "average": 4.0}
    assert body["midterm"] == {"count": 1, "average": 5.0}
    assert body["final"] == {"count": 0, "average": None}
    assert body["semester_mark"] == 4.5  # lesson 4.0 and midterm 5.0: no final yet
    assert body["components"] == ["lesson", "midterm"]
    assert body["missing"] == ["final"]
    assert body["remaining"] == {"midterm": 1, "final": 1}
    assert body["pending"] == ["midterm", "final"]
    # Remaining controls are guessed as 4: (4.00 + (5 + 4) / 2 + 4) / 3 = 4.17
    assert body["predicted"] == {"value": 4.17, "midterm": 4, "final": 4}
    assert body["assumptions"] == [
        "rounding",
        "controls_per_semester",
        "pending_as_lesson_average",
    ]
    assert body["what_if"] == []
    five, four, three = body["targets"]
    assert (five["grade"], five["threshold"], five["status"]) == (5, 4.5, "needed")
    assert (five["min_both"], five["control"], five["min_value"]) == (5, None, None)
    assert five["pairs"] == [
        {"midterm": 5, "min_final": 5},
        {"midterm": 4, "min_final": 5},
        {"midterm": 3, "min_final": None},
        {"midterm": 2, "min_final": None},
    ]
    assert (four["grade"], four["status"], four["min_both"]) == (4, "needed", 3)
    assert four["pairs"] == [
        {"midterm": 5, "min_final": 2},
        {"midterm": 4, "min_final": 2},
        {"midterm": 3, "min_final": 3},
        {"midterm": 2, "min_final": 3},
    ]
    assert (three["grade"], three["status"], three["pairs"]) == (3, "secured", [])


async def test_what_if_marks_change_the_answer_without_saving_anything(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """A second midterm 4 and a final 5: nothing is left to come, and a 5 is secured."""
    actor = make_actor(Role.STUDENT, user_id=env.world.user_id)

    response = await _get(
        http_client,
        services,
        actor,
        env.world.math_id,
        [("what_if", "midterm:4"), ("what_if", "final:5")],
    )
    plain = await _get(http_client, services, actor, env.world.math_id)

    body = response.json()
    assert body["midterm"] == {"count": 2, "average": 4.5}
    assert body["final"] == {"count": 1, "average": 5.0}
    assert body["semester_mark"] == 4.5  # (4.00 + 4.50 + 5.00) / 3 = 4.5
    assert body["components"] == ["lesson", "midterm", "final"]
    assert body["missing"] == []
    assert body["remaining"] == {"midterm": 0, "final": 0}
    assert body["pending"] == []
    assert [t["status"] for t in body["targets"]] == ["secured"] * 3
    assert body["what_if"] == [
        {"type": "midterm", "value": 4},
        {"type": "final", "value": 5},
    ]
    assert "what_if" in body["assumptions"]
    assert plain.json()["midterm"]["count"] == 1  # the real marks are untouched


async def test_a_what_if_lesson_mark_moves_the_average(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """A fourth lesson mark of 5 lifts the lesson average from 4.00 to 4.25."""
    actor = make_actor(Role.STUDENT, user_id=env.world.user_id)

    response = await _get(
        http_client, services, actor, env.world.math_id, {"what_if": "lesson:5"}
    )

    assert response.json()["lesson"] == {"count": 4, "average": 4.25}


async def test_a_subject_with_only_lesson_marks_has_both_kinds_remaining(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """Physics has one lesson mark of 3: two midterms and the final are all to come."""
    actor = make_actor(Role.STUDENT, user_id=env.world.user_id)

    body = (await _get(http_client, services, actor, env.world.physics_id)).json()

    assert body["semester_mark"] == 3.0
    assert body["components"] == ["lesson"]
    assert body["missing"] == ["midterm", "final"]
    assert body["remaining"] == {"midterm": 2, "final": 1}
    assert "same_mark_on_remaining" in body["assumptions"]
    five = body["targets"][0]
    assert (five["status"], five["min_both"], five["pairs"]) == (
        "not_reachable",
        None,
        [],
    )


async def test_bad_what_if_values_are_a_validation_error(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """422 for an unknown type, a mark outside 2..5 or over 500 marks."""
    actor = make_actor(Role.STUDENT, user_id=env.world.user_id)

    for raw in ("exam:4", "lesson:6", "lesson", "lesson:x"):
        response = await _get(
            http_client, services, actor, env.world.math_id, {"what_if": raw}
        )
        assert response.status_code == 422, raw
        assert response.json()["type"] == "academic/invalid-what-if"
    too_many = [("what_if", "lesson:5")] * 501
    response = await _get(http_client, services, actor, env.world.math_id, too_many)
    assert response.status_code == 422


async def test_a_foreign_subject_is_not_found_and_teachers_are_refused(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """404 outside the curriculum; the route is for students."""
    student = make_actor(Role.STUDENT, user_id=env.world.user_id)
    teacher = make_actor(Role.TEACHER, user_id=env.world.teacher_id)

    missing = await _get(http_client, services, student, uuid4())
    refused = await _get(http_client, services, teacher, env.world.math_id)

    assert missing.status_code == 404
    assert missing.json()["type"] == "academic/subject-not-found"
    assert refused.status_code == 403


async def test_an_unknown_student_is_not_found(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """A user without a student record has no planner."""
    stranger = make_actor(Role.STUDENT, user_id=uuid4())

    response = await _get(http_client, services, stranger, env.world.math_id)

    assert response.status_code == 404


async def test_the_use_case_returns_plain_python_values(
    services: MarksServices, env: Env, make_actor: Any
) -> None:
    """Called directly (as the MCP tools could): floats, lists and no Decimals."""
    actor = make_actor(Role.STUDENT, user_id=env.world.user_id)

    body = await services.get_subject_planner.execute(
        actor, env.world.math_id, None, [parse_what_if("final:5")]
    )

    assert body["semester"] == 3  # the student's current semester
    assert body["final"] == {"count": 1, "average": 5.0}
    assert body["semester_mark"] == 4.67  # (4.00 + 5.00 + 5.00) / 3
    assert body["what_if"] == [{"type": "final", "value": 5}]
    assert isinstance(body["targets"][0]["threshold"], float)
