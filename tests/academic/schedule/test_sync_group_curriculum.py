"""Group curriculum from EMIS: storing it, filling names, creating terms."""

import datetime as dt
from dataclasses import replace
from types import SimpleNamespace

from app.bootstrap.worker import task_modules
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.schedule import CRON_JOBS
from app.interfaces.jobs.tasks.academic.sync_group_curriculum import (
    sync_group_curriculum,
)
from app.modules.academic.domain.schedule.errors import (
    CurriculumNoEmisStudentError,
    GroupNotFoundError,
)
from app.modules.academic.domain.schedule.term import Term
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisCredentialsMissing,
    EmisName,
    EmisUnavailable,
)
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from tests.academic.schedule.curriculum_builders import (
    ENGLISH,
    MATH,
    PHYSICS,
    make_curriculum,
    semester_subject,
)
from tests.academic.schedule.env import Env
from tests.fakes.academic.schedule.identity import make_user

import pytest

D = dt.date.fromisoformat


async def _terms(env: Env) -> list[Term]:
    async with env.uow_factory() as uow:
        return await uow.terms.list_all()


# - - - storing - - -


async def test_the_curriculum_is_stored_for_the_group(env: Env) -> None:
    """The header, the semester dates and the subjects of each semester."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()

    result = await env.emis_import.sync_group_curriculum.execute(group.id)

    assert (result.status, result.group_id, result.subjects) == ("synced", group.id, 5)
    async with env.uow_factory() as uow:
        header = await uow.curricula.get(group.id)
        rows = await uow.curricula.list_subjects(group.id)
        listed = await uow.curricula.group_ids()
    assert header is not None
    assert (header.emis_curriculum_id, header.name) == (2124, "TN, MTN 2025-2027")
    assert header.fetched_at == env.clock.now()
    assert (header.edu_form, header.language_code) == ("Kunduzgi", "uz")
    assert [s.number for s in header.semester_dates] == [1, 2, 3, 4]
    assert header.semester_dates[2].starts_on == D("2026-09-01")
    assert [(r.semester_number, r.emis_subject_id) for r in rows] == [
        (3, MATH),
        (3, PHYSICS),
        (3, ENGLISH),
        (4, MATH),
        (4, PHYSICS),
    ]
    assert rows[2].name == {"uz": "Ingliz tili", "ru": "", "en": "English"}
    assert rows[2].is_separated is True
    assert listed == [group.id]


async def test_a_new_sync_replaces_the_stored_curriculum(env: Env) -> None:
    """Subjects EMIS no longer lists go; the header follows the new answer."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()
    await env.emis_import.sync_group_curriculum.execute(group.id)
    env.clock.advance(hours=24)
    env.emis.curriculum_result = make_curriculum(
        emis_id=2200,
        semester_subjects=(semester_subject(3, MATH, EmisName(uz="Matematika")),),
    )

    await env.emis_import.sync_group_curriculum.execute(group.id)

    async with env.uow_factory() as uow:
        header = await uow.curricula.get(group.id)
        rows = await uow.curricula.list_subjects(group.id)
    assert header is not None and header.emis_curriculum_id == 2200
    assert header.fetched_at == env.clock.now()
    assert [(r.semester_number, r.emis_subject_id) for r in rows] == [(3, MATH)]


async def test_the_group_ids_with_a_curriculum_are_listed(env: Env) -> None:
    """Only groups that were synced."""
    synced = await env.group("2TN2")
    await env.student(synced)
    await env.group("3TN1")
    env.emis.curriculum_result = make_curriculum()

    await env.emis_import.sync_group_curriculum.execute(synced.id)

    async with env.uow_factory() as uow:
        assert await uow.curricula.group_ids() == [synced.id]
        assert await uow.curricula.exists(synced.id) is True


# - - - names - - -


async def test_empty_names_of_existing_subjects_are_filled_never_overwritten(
    env: Env,
) -> None:
    """The Russian name stays as it is; the empty uz and en come from EMIS."""
    group = await env.group()
    await env.student(group)
    math = await env.subject("Математика (наш)", short="Мат", emis_id=MATH)
    env.emis.curriculum_result = make_curriculum()

    result = await env.emis_import.sync_group_curriculum.execute(group.id)

    async with env.uow_factory() as uow:
        stored = await uow.subjects.get(math.id)
    assert stored is not None
    assert stored.name == {
        "uz": "Matematika",
        "ru": "Математика (наш)",
        "en": "Mathematics",
    }
    assert stored.short_name == "Мат"
    assert result.names_filled == 1


async def test_a_subject_with_every_name_is_left_untouched(env: Env) -> None:
    """Nothing to fill: no write and no change."""
    group = await env.group()
    await env.student(group)
    physics = await env.subject("Другая физика", emis_id=PHYSICS)
    async with env.uow_factory() as uow:
        physics.name = {"uz": "Boshqa", "ru": "Другая физика", "en": "Other"}
        await uow.subjects.save(physics)
        await uow.commit()
    env.emis.curriculum_result = make_curriculum()

    await env.emis_import.sync_group_curriculum.execute(group.id)

    async with env.uow_factory() as uow:
        stored = await uow.subjects.get(physics.id)
    assert stored is not None
    assert stored.name == {"uz": "Boshqa", "ru": "Другая физика", "en": "Other"}


async def test_no_subject_is_created_by_the_curriculum(env: Env) -> None:
    """Subjects come from the subjects sync; the curriculum only fills names."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()

    await env.emis_import.sync_group_curriculum.execute(group.id)

    async with env.uow_factory() as uow:
        assert await uow.subjects.search(None) == []
    assert env.kicker.calls == []  # and no translation is started


# - - - terms - - -


async def test_semesters_without_a_term_get_one_and_an_overlapping_term_is_kept(
    env: Env,
) -> None:
    """Semester 3 overlaps the term Administration made; the others are created."""
    group = await env.group()
    await env.student(group)
    mine = await env.term(bells=[])
    env.emis.curriculum_result = make_curriculum()

    result = await env.emis_import.sync_group_curriculum.execute(group.id)

    terms = await _terms(env)
    assert result.terms_created == 3
    assert [(t.academic_year, t.half, t.starts_on, t.ends_on) for t in terms] == [
        ("2025-2026", 1, D("2025-09-01"), D("2025-12-27")),
        ("2025-2026", 2, D("2026-01-12"), D("2026-05-30")),
        ("2026-2027", 1, mine.starts_on, mine.ends_on),
        ("2026-2027", 2, D("2027-01-11"), D("2027-05-29")),
    ]
    assert terms[2].id == mine.id
    created = [t for t in terms if t.id != mine.id]
    assert all(
        t.bells == [] and t.non_study_days == [] and t.moved_days == [] for t in created
    )
    assert all(t.control_periods.items() == [] for t in created)


async def test_a_term_with_the_same_year_and_half_is_skipped(env: Env) -> None:
    """The year and half are taken by a term elsewhere in time: no duplicate."""
    group = await env.group()
    await env.student(group)
    taken = await env.term(
        academic_year="2025-2026",
        half=1,
        starts_on=D("2024-09-01"),
        ends_on=D("2024-12-20"),
        bells=[],
    )
    env.emis.curriculum_result = make_curriculum()

    result = await env.emis_import.sync_group_curriculum.execute(group.id)

    terms = await _terms(env)
    assert result.terms_created == 3  # semesters 2, 3 and 4
    assert [(t.academic_year, t.half) for t in terms] == [
        ("2025-2026", 1),
        ("2025-2026", 2),
        ("2026-2027", 1),
        ("2026-2027", 2),
    ]
    assert terms[0].id == taken.id and terms[0].starts_on == D("2024-09-01")


async def test_a_second_sync_creates_no_more_terms(env: Env) -> None:
    """The terms made the first time cover every semester now."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()
    first = await env.emis_import.sync_group_curriculum.execute(group.id)

    second = await env.emis_import.sync_group_curriculum.execute(group.id)

    assert (first.terms_created, second.terms_created) == (4, 0)
    assert len(await _terms(env)) == 4


async def test_a_second_group_with_the_same_dates_adds_no_terms(env: Env) -> None:
    """All groups of a lyceum share the semesters."""
    first_group = await env.group("2TN2")
    second_group = await env.group("2TN1")
    await env.student(first_group)
    await env.student(second_group, first_name="Bobur", last_name="Aliev")
    env.emis.curriculum_result = make_curriculum()

    await env.emis_import.sync_group_curriculum.execute(first_group.id)
    again = await env.emis_import.sync_group_curriculum.execute(second_group.id)

    assert again.terms_created == 0
    assert len(await _terms(env)) == 4


async def test_a_semester_with_reversed_dates_is_skipped(env: Env) -> None:
    """The term rules reject it; the other semesters are still created."""
    group = await env.group()
    await env.student(group)
    broken = make_curriculum().semesters[:2] + (
        type(make_curriculum().semesters[0])(3, D("2026-12-26"), D("2026-09-01")),
    )
    env.emis.curriculum_result = make_curriculum(semesters=broken)

    result = await env.emis_import.sync_group_curriculum.execute(group.id)

    assert result.terms_created == 2
    assert [t.half for t in await _terms(env)] == [1, 2]


# - - - which student answers - - -


async def test_a_group_without_a_usable_student_has_no_curriculum_to_read(
    env: Env,
) -> None:
    """Left, unregistered and needs-reauth students cannot fetch the curriculum."""
    group = await env.group()
    await env.student(group, status="left")
    await env.student(
        group,
        first_name="Bobur",
        last_name="Aliev",
        user_status=UserStatus.UNREGISTERED,
    )
    reauth = await env.student(group, first_name="Dilnoza", last_name="Rustamova")
    env.identity.users[reauth.id] = replace(reauth, emis_status="needs_reauth")
    env.emis.curriculum_result = make_curriculum()

    with pytest.raises(CurriculumNoEmisStudentError):
        await env.emis_import.sync_group_curriculum.execute(group.id)

    assert env.emis.calls == []
    async with env.uow_factory() as uow:
        assert await uow.curricula.get(group.id) is None
    assert await _terms(env) == []


async def test_the_hook_path_answers_no_student_and_does_not_fail(env: Env) -> None:
    """ensure runs in the profile refresh: no student is no_student, not an error."""
    group = await env.group()

    result = await env.emis_import.sync_group_curriculum.ensure(group.id)

    assert result is not None
    assert (result.status, result.subjects) == ("no_student", 0)
    assert env.emis.calls == []


async def test_a_student_whose_credentials_are_rejected_is_skipped(env: Env) -> None:
    """EMIS answers 401 for the first student; the next one is tried."""
    group = await env.group()
    first = await env.student(group)
    second = await env.student(group, first_name="Bobur", last_name="Aliev")
    ordered = sorted([first.id, second.id])
    env.emis.curriculum_errors[ordered[0]] = EmisAuthFailed()
    env.emis.curriculum_result = make_curriculum()

    result = await env.emis_import.sync_group_curriculum.execute(group.id)

    assert result.status == "synced"
    assert env.emis.calls == [("curriculum", ordered[0]), ("curriculum", ordered[1])]


async def test_a_student_without_a_stored_login_is_skipped(env: Env) -> None:
    """Vault has no secret for the first student: the next student answers."""
    group = await env.group()
    first = await env.student(group)
    second = await env.student(group, first_name="Bobur", last_name="Aliev")
    ordered = sorted([first.id, second.id])
    env.emis.curriculum_errors[ordered[0]] = EmisCredentialsMissing()
    env.emis.curriculum_result = make_curriculum()

    result = await env.emis_import.sync_group_curriculum.execute(group.id)

    assert result.status == "synced"
    assert env.emis.calls == [("curriculum", ordered[0]), ("curriculum", ordered[1])]


async def test_no_usable_login_in_the_group_means_no_student_and_nothing_stored(
    env: Env,
) -> None:
    """Five students at most are tried; then no student can be used (409)."""
    group = await env.group()
    for index in range(6):
        await env.student(group, first_name=f"Name{index}", last_name=f"Surname{index}")
    env.emis.curriculum_error = EmisCredentialsMissing()

    with pytest.raises(CurriculumNoEmisStudentError):
        await env.emis_import.sync_group_curriculum.execute(group.id)

    assert len(env.emis.calls) == 5
    async with env.uow_factory() as uow:
        assert await uow.curricula.exists(group.id) is False


async def test_an_unavailable_emis_raises_and_stores_nothing(env: Env) -> None:
    """EmisUnavailable is for the caller (the task fails, the admin sees 503)."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_error = EmisUnavailable()

    with pytest.raises(EmisUnavailable):
        await env.emis_import.sync_group_curriculum.execute(group.id)

    async with env.uow_factory() as uow:
        assert await uow.curricula.exists(group.id) is False


async def test_an_unknown_group_is_not_found(env: Env) -> None:
    """Nothing to sync for a group that does not exist."""
    with pytest.raises(GroupNotFoundError):
        await env.emis_import.sync_group_curriculum.execute(new_id())


# - - - one-time fetch and the admin refresh - - -


async def test_ensure_fetches_once_and_then_leaves_a_stored_curriculum_alone(
    env: Env,
) -> None:
    """The hook path reads the curriculum when there is none, never again."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()
    service = env.emis_import.sync_group_curriculum

    first = await service.ensure(group.id)
    second = await service.ensure(group.id)

    assert first is not None and first.status == "synced"
    assert second is None
    assert len(env.emis.calls) == 1


async def test_the_admin_refresh_fetches_even_when_a_curriculum_is_stored(
    env: Env,
) -> None:
    """execute is what the admin button runs: it always asks EMIS."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()
    service = env.emis_import.sync_group_curriculum
    await service.ensure(group.id)
    env.emis.curriculum_result = make_curriculum(emis_id=3000)

    refreshed = await service.execute(group.id)

    assert refreshed.status == "synced"
    assert len(env.emis.calls) == 2
    async with env.uow_factory() as uow:
        header = await uow.curricula.get(group.id)
    assert header is not None and header.emis_curriculum_id == 3000


async def test_enrollment_asks_for_a_curriculum_until_the_group_has_one(
    env: Env,
) -> None:
    """StudentRef.needs_curriculum is true for a group without a stored curriculum."""
    enrollment = env.services.enrollment
    user = env.identity.add(make_user(login="aliya.karimova"))
    ref = await enrollment.ensure_student(
        user_id=user.id,
        group_emis_id=3292,
        group_name="2TN2",
        current_semester=3,
        curriculum_id=1,
    )
    env.emis.curriculum_result = make_curriculum()
    await env.emis_import.sync_group_curriculum.execute(ref.group_id)

    after = await enrollment.ensure_student(
        user_id=user.id,
        group_emis_id=3292,
        group_name="2TN2",
        current_semester=3,
        curriculum_id=1,
    )

    assert ref.needs_curriculum is True
    assert after.needs_curriculum is False


# - - - the task and the schedule - - -


@pytest.fixture
def worker_container(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """What bootstrap/worker.py would set: a container with the EMIS import."""
    container = SimpleNamespace(academic=SimpleNamespace(emis_import=env.emis_import))
    monkeypatch.setattr("app.interfaces.jobs.context._container", container)


@pytest.mark.usefixtures("worker_container")
async def test_the_task_fetches_a_missing_curriculum_once(env: Env) -> None:
    """academic.sync_group_curriculum: "synced" the first time, "exists" after."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()

    first = await sync_group_curriculum(group.id)
    second = await sync_group_curriculum(group.id)

    assert (first, second) == ("synced", "exists")
    assert len(env.emis.calls) == 1


def test_the_task_is_registered_and_no_cron_job_refreshes_curricula() -> None:
    """The curriculum is fetched once; refreshing it is the administrator's button."""
    task_modules()

    assert broker.find_task("academic.sync_group_curriculum") is not None
    assert not any("curricul" in job.task_name for job in CRON_JOBS)
