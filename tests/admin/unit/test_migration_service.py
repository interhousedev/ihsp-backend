"""Server migration: the state machine, permissions, step-up, audit and secrecy."""

import json
from dataclasses import replace

from app.modules.admin.domain.errors import (
    MigrationInvalidInputError,
    MigrationNotAllowedError,
    MigrationNotConfiguredError,
)
from app.modules.admin.domain.migration import (
    STEPS,
    MigrationEvent,
    MigrationPhase,
    in_maintenance,
    transition,
    validate_target,
    validate_token,
)
from app.shared.base_error import ForbiddenError
from tests.admin.migration_support import ADMIN, TEACHER, TOKEN, Rig

import pytest


async def test_start_queues_the_request_and_enters_maintenance() -> None:
    rig = Rig()

    state = await rig.start()

    assert state.phase is MigrationPhase.QUEUED
    assert rig.store.request is not None
    assert rig.store.request.pairing_token == TOKEN
    assert rig.service.info().active is True
    assert rig.service.info().moved is False


async def test_start_audits_without_the_token() -> None:
    rig = Rig()

    state = await rig.start()

    (draft,) = rig.audits
    assert draft.type == "admin.migration_started"
    assert draft.metadata["migration_id"] == state.id
    assert TOKEN not in json.dumps(draft.metadata, default=str)
    assert TOKEN not in repr(rig.store.state)


async def test_only_an_admin_may_use_it() -> None:
    rig = Rig()

    with pytest.raises(ForbiddenError):
        await rig.service.start(
            TEACHER,
            target_host="new.example.org",
            target_port=22,
            pairing_token=TOKEN,
            target_url=None,
            otp_code="123456",
        )
    with pytest.raises(ForbiddenError):
        await rig.service.status(TEACHER)
    with pytest.raises(ForbiddenError):
        await rig.service.rollback(TEACHER, otp_code="123456")
    assert rig.store.request is None


async def test_a_wrong_step_up_code_queues_nothing() -> None:
    rig = Rig()

    with pytest.raises(PermissionError):
        await rig.start(otp_code="000000")

    assert rig.store.request is None and rig.store.state is None
    assert rig.audits == []
    assert rig.service.info().active is False


async def test_not_configured_refuses_to_start() -> None:
    rig = Rig(available=False)

    with pytest.raises(MigrationNotConfiguredError):
        await rig.start()
    assert rig.service.configured() is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_host": "-oProxyCommand=x"},
        {"target_host": "a b"},
        {"target_port": 0},
        {"target_url": "http://new.example.org"},
        {"pairing_token": "short"},
        {"pairing_token": "ihsp-pair-v1." + "A" * 70 + " ;rm"},
    ],
)
async def test_malformed_input_is_refused(overrides: dict[str, object]) -> None:
    rig = Rig()

    with pytest.raises(MigrationInvalidInputError):
        await rig.start(**overrides)
    assert rig.store.request is None


async def test_a_second_start_is_refused() -> None:
    rig = Rig()
    await rig.start()

    with pytest.raises(MigrationNotAllowedError):
        await rig.start()


async def test_runner_reports_drive_the_phases_and_progress() -> None:
    rig = Rig()
    await rig.start()

    rig.store.report("running", step=STEPS[1], steps_done=(STEPS[0],))
    rig.tick()
    state = await rig.service.status(ADMIN)
    assert state is not None
    assert state.phase is MigrationPhase.RUNNING
    assert state.step == STEPS[1] and state.steps_done == (STEPS[0],)

    rig.store.report("running", step=STEPS[2], steps_done=STEPS[:2])
    rig.tick()
    state = await rig.service.status(ADMIN)
    assert state is not None and state.step == STEPS[2]

    rig.store.report("completed", steps_done=STEPS)
    rig.tick()
    state = await rig.service.status(ADMIN)
    assert state is not None and state.phase is MigrationPhase.COMPLETED
    info = rig.service.info()
    assert info.active and info.moved and info.target_url == "https://new.example.org"


async def test_the_target_url_stays_hidden_until_the_copy_is_done() -> None:
    rig = Rig()
    await rig.start()
    rig.store.report("running", step=STEPS[0])
    rig.tick()

    assert rig.service.info().target_url is None


async def test_failure_keeps_maintenance_until_rollback() -> None:
    rig = Rig()
    await rig.start()
    rig.store.report("failed", step=STEPS[3], error="rsync exited 23")
    rig.tick()

    state = await rig.service.status(ADMIN)
    assert state is not None and state.phase is MigrationPhase.FAILED
    assert state.error == "rsync exited 23"
    assert rig.service.info().active is True

    assert await rig.service.rollback(ADMIN, otp_code="123456") is None
    rig.tick()
    assert rig.service.info().active is False
    assert rig.store.state is None


async def test_rollback_of_a_queued_request_asks_the_runner_to_cancel() -> None:
    rig = Rig()
    await rig.start()

    result = await rig.service.rollback(ADMIN, otp_code="123456")

    assert result is not None and result.phase is MigrationPhase.CANCELLING
    assert rig.store.command is not None and rig.store.command[1] == "cancel"
    assert rig.service.info().active is True
    assert [a.type for a in rig.audits] == [
        "admin.migration_started",
        "admin.migration_rollback",
    ]


async def test_rollback_of_a_running_copy_asks_the_runner_to_cancel() -> None:
    rig = Rig()
    state = await rig.start()
    rig.store.report("running", step=STEPS[1])
    rig.tick()

    result = await rig.service.rollback(ADMIN, otp_code="123456")

    assert result is not None and result.phase is MigrationPhase.CANCELLING
    assert rig.store.command == (state.id, "cancel")
    assert rig.service.info().active is True
    rig.store.report("cancelled")
    rig.tick()
    await rig.service.status(ADMIN)
    assert rig.service.info().active is False


async def test_rollback_after_completion_resumes_the_source() -> None:
    rig = Rig()
    state = await rig.start()
    rig.store.report("completed", steps_done=STEPS)
    rig.tick()
    await rig.service.status(ADMIN)

    result = await rig.service.rollback(ADMIN, otp_code="123456")

    assert result is not None and result.phase is MigrationPhase.CANCELLING
    assert rig.store.command == (state.id, "resume")
    rig.store.report("cancelled")
    rig.tick()
    assert (await rig.service.status(ADMIN)) is None


async def test_rollback_with_nothing_to_roll_back_is_refused() -> None:
    rig = Rig()

    with pytest.raises(MigrationNotAllowedError):
        await rig.service.rollback(ADMIN, otp_code="123456")


async def test_a_report_for_another_migration_is_ignored() -> None:
    rig = Rig()
    await rig.start()
    rig.store.report("completed")
    assert rig.store.status is not None
    rig.store.status = replace(rig.store.status, id="old")
    rig.tick()

    state = await rig.service.status(ADMIN)
    assert state is not None and state.phase is MigrationPhase.QUEUED


async def test_a_long_queued_request_is_flagged_stale() -> None:
    rig = Rig()
    state = await rig.start()
    assert rig.service.is_stale(state) is False

    rig.clock.advance(minutes=3)
    assert rig.service.is_stale(state) is True


def test_transition_table_and_maintenance_flag() -> None:
    assert (
        transition(MigrationPhase.IDLE, MigrationEvent.START) is MigrationPhase.QUEUED
    )
    with pytest.raises(MigrationNotAllowedError):
        transition(MigrationPhase.COMPLETED, MigrationEvent.START)
    with pytest.raises(MigrationNotAllowedError):
        transition(MigrationPhase.IDLE, MigrationEvent.ROLLBACK)
    assert not in_maintenance(MigrationPhase.IDLE)
    assert all(
        in_maintenance(p) for p in MigrationPhase if p is not MigrationPhase.IDLE
    )


def test_validation_helpers() -> None:
    assert validate_target("203.0.113.7", 22, "https://x.example.org/") == (
        "https://x.example.org"
    )
    assert validate_target("new.example.org", 2222, None) is None
    validate_token(TOKEN)
