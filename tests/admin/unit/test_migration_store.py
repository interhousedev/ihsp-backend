"""The file store of the migration: round trip, 0600 files, tolerant reads."""

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

from app.modules.admin.domain.migration import (
    MigrationPhase,
    MigrationState,
    RunnerRequest,
)
from app.modules.admin.infrastructure.migration_store import FileMigrationStore

NOW = datetime(2026, 10, 6, 9, tzinfo=UTC)


def _state() -> MigrationState:
    return MigrationState(
        id="abc",
        phase=MigrationPhase.RUNNING,
        target_host="h",
        target_port=22,
        target_url=None,
        requested_by="u",
        requested_at=NOW,
        updated_at=NOW,
        step="dump_postgres",
        steps_done=("stop_services",),
    )


def test_off_without_a_directory(tmp_path: Path) -> None:
    assert FileMigrationStore(None).available() is False
    assert FileMigrationStore(tmp_path / "missing").available() is False
    assert FileMigrationStore(None).read_state() is None


def test_state_round_trip(tmp_path: Path) -> None:
    store = FileMigrationStore(tmp_path)

    store.write_state(_state())

    assert store.read_state() == _state()
    store.clear_state()
    assert store.read_state() is None


def test_request_holds_the_token_in_a_private_file(tmp_path: Path) -> None:
    store = FileMigrationStore(tmp_path)

    store.queue_request(RunnerRequest("abc", "h", 22, "ihsp-pair-v1.xyz", NOW))

    path = tmp_path / "request.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["pairing_token"] == "ihsp-pair-v1.xyz"
    store.withdraw_request()
    assert not path.exists()


def test_state_file_never_holds_the_token(tmp_path: Path) -> None:
    store = FileMigrationStore(tmp_path)
    store.write_state(_state())
    store.queue_request(RunnerRequest("abc", "h", 22, "ihsp-pair-v1.xyz", NOW))

    assert "pairing" not in (tmp_path / "state.json").read_text()


def test_garbage_files_read_as_absent(tmp_path: Path) -> None:
    store = FileMigrationStore(tmp_path)
    (tmp_path / "state.json").write_text("{not json")
    (tmp_path / "status.json").write_text('{"id": 1}')

    assert store.read_state() is None
    assert store.read_status() is None


def test_status_is_read_from_the_runner_file(tmp_path: Path) -> None:
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "id": "abc",
                "state": "running",
                "step": "copy_objects",
                "steps_done": ["stop_services"],
                "error": None,
                "updated_at": NOW.isoformat(),
                "dry_run": True,
            }
        )
    )

    status = FileMigrationStore(tmp_path).read_status()

    assert status is not None and status.step == "copy_objects" and status.dry_run


def test_commands_are_queued(tmp_path: Path) -> None:
    FileMigrationStore(tmp_path).queue_command("abc", "cancel")

    assert json.loads((tmp_path / "command.json").read_text()) == {
        "id": "abc",
        "action": "cancel",
    }
