"""The host runner of the server migration, in dry-run mode (no Docker, no network)."""

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "migrate_runner.sh"
TARGET = ROOT / "scripts" / "migrate_target.sh"
SECRET = "SUPER-SECRET-PRIVATE-KEY-MATERIAL"
STEPS = [
    "stop_services",
    "dump_postgres",
    "snapshot_redis",
    "copy_objects",
    "copy_config",
    "copy_vault",
    "copy_backups",
    "count_rows",
    "transfer",
    "verify",
]


def _token() -> str:
    body = json.dumps(
        {
            "user": "ihsp-migrate",
            "port": 22,
            "key": SECRET,
            "host_key": "ssh-ed25519 AAA",
        }
    )
    return "ihsp-pair-v1." + base64.urlsafe_b64encode(body.encode()).decode()


def _run(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "IHSP_MIGRATION_DIR": str(tmp),
        "IHSP_ROOT": str(tmp / "root"),
        "IHSP_MIGRATION_WORK": str(tmp / "work"),
    }
    return subprocess.run(
        ["bash", str(RUNNER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _queue(tmp: Path, **extra: object) -> None:
    request = {
        "id": "m-1",
        "target_host": "new.example.com",
        "target_port": 22,
        "pairing_token": _token(),
        "requested_at": "2026-01-01T00:00:00+00:00",
        "dry_run": True,
        **extra,
    }
    path = tmp / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    path.chmod(0o600)


def _status(tmp: Path) -> dict[str, object]:
    return json.loads((tmp / "status.json").read_text(encoding="utf-8"))


def test_scripts_are_valid_shell() -> None:
    for script in (RUNNER, TARGET):
        done = subprocess.run(["bash", "-n", str(script)], capture_output=True)
        assert done.returncode == 0, done.stderr


def test_a_dry_run_walks_every_step_and_consumes_the_request(tmp_path: Path) -> None:
    _queue(tmp_path)
    done = _run(tmp_path, "run", "--dry-run")
    assert done.returncode == 0, done.stderr
    status = _status(tmp_path)
    assert status["state"] == "completed"
    assert status["dry_run"] is True
    assert status["id"] == "m-1"
    assert status["steps_done"] == STEPS
    assert not (tmp_path / "request.json").exists()


def test_the_token_never_reaches_output_or_status(tmp_path: Path) -> None:
    _queue(tmp_path)
    done = _run(tmp_path, "run", "--dry-run")
    leaked = _token()
    for text in (
        done.stdout,
        done.stderr,
        (tmp_path / "status.json").read_text(encoding="utf-8"),
    ):
        assert leaked not in text
        assert SECRET not in text


def test_a_bad_token_fails_the_run_with_a_message(tmp_path: Path) -> None:
    _queue(tmp_path, pairing_token="not-a-token")
    done = _run(tmp_path, "run", "--dry-run")
    assert done.returncode != 0
    status = _status(tmp_path)
    assert status["state"] == "failed"
    assert status["error"]
    assert "not-a-token" not in json.dumps(status)


def test_a_cancel_command_stops_a_queued_run(tmp_path: Path) -> None:
    _queue(tmp_path)
    (tmp_path / "command.json").write_text(
        json.dumps({"action": "cancel", "id": "m-1"}), encoding="utf-8"
    )
    done = _run(tmp_path, "run", "--dry-run")
    assert done.returncode == 0, done.stderr
    assert _status(tmp_path)["state"] == "cancelled"
    assert not (tmp_path / "command.json").exists()


def test_a_resume_command_reports_cancelled(tmp_path: Path) -> None:
    (tmp_path / "command.json").write_text(
        json.dumps({"action": "resume", "id": "m-1"}), encoding="utf-8"
    )
    done = _run(tmp_path, "run", "--dry-run")
    assert done.returncode == 0, done.stderr
    assert _status(tmp_path)["state"] == "cancelled"


def test_nothing_to_do_is_a_quiet_success(tmp_path: Path) -> None:
    assert _run(tmp_path, "run", "--dry-run").returncode == 0
    assert not (tmp_path / "status.json").exists()


@pytest.mark.parametrize("script", [RUNNER, TARGET])
def test_scripts_are_executable(script: Path) -> None:
    assert os.access(script, os.X_OK)


@pytest.mark.parametrize(
    "extra",
    [
        {"target_host": "-oProxyCommand=x"},
        {"target_host": "a b"},
        {"id": "-m"},
        {"target_port": 0},
    ],
)
def test_the_runner_revalidates_the_request(
    tmp_path: Path, extra: dict[str, object]
) -> None:
    _queue(tmp_path, **extra)
    done = _run(tmp_path, "run", "--dry-run")
    assert done.returncode != 0
    assert _status(tmp_path)["state"] == "failed"


@pytest.mark.parametrize("body", ["{}", '{"id": "m-1", "action": "bogus"}'])
def test_an_unknown_command_is_dropped(tmp_path: Path, body: str) -> None:
    (tmp_path / "command.json").write_text(body, encoding="utf-8")
    assert _run(tmp_path, "run", "--dry-run").returncode == 0
    assert not (tmp_path / "command.json").exists()
