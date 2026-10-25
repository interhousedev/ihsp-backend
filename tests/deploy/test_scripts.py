"""Shell scripts and helper files of the deployment: syntax, modes, safety."""

import os
import subprocess
from pathlib import Path

from tests.deploy.helpers import MATERIALS_DIR, SCRIPTS_DIR

import pytest

OWNED_SCRIPTS = (
    "local_up.sh",
    "local_down.sh",
    "prod_init.sh",
    "cloud_deploy.sh",
    "backup.sh",
    "backup_bugsink.sh",
    "restore.sh",
)
SHELL_FILES = [
    *(SCRIPTS_DIR / name for name in OWNED_SCRIPTS),
    MATERIALS_DIR / "postgres" / "init-hydra.sh",
    MATERIALS_DIR / "certbot" / "deploy-hook.sh",
]


@pytest.mark.parametrize("script", SHELL_FILES, ids=lambda path: path.name)
def test_shell_syntax_is_valid(script: Path) -> None:
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", SHELL_FILES, ids=lambda path: path.name)
def test_shell_files_are_executable_and_strict(script: Path) -> None:
    assert os.access(script, os.X_OK), f"{script} is not executable"
    assert "set -e" in script.read_text(encoding="utf-8")


def test_healthcheck_helper_compiles() -> None:
    source = (MATERIALS_DIR / "healthcheck" / "check.py").read_text(encoding="utf-8")
    compile(source, "check.py", "exec")


def test_healthcheck_helper_reports_a_missing_process() -> None:
    check = MATERIALS_DIR / "healthcheck" / "check.py"
    result = subprocess.run(
        ["python3", str(check), "proc", "no-such-process-token-i4"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1


def test_healthcheck_helper_rejects_unknown_probes() -> None:
    check = MATERIALS_DIR / "healthcheck" / "check.py"
    result = subprocess.run(
        ["python3", str(check), "nonsense"], capture_output=True, check=False
    )
    assert result.returncode == 2


def test_no_script_runs_docker_against_the_dev_project() -> None:
    for name in OWNED_SCRIPTS:
        text = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
        assert "ihsp-dev" not in text, name
        assert "docker-compose.dev.yaml" not in text, name
