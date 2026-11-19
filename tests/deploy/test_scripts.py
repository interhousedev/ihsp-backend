"""Shell scripts and helper files of the deployment: syntax, modes, safety."""

import importlib.util
import os
import re
import subprocess
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

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


def test_prod_init_can_read_every_credential_vault_setup_prints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """prod_init.sh greps `KEY=value` lines out of `setup.py --print-credentials`."""
    script = (SCRIPTS_DIR / "prod_init.sh").read_text(encoding="utf-8")
    wanted = re.findall(r"\"\$out\" \| sed -n 's/\^([A-Z_]+)=//p'", script)
    assert set(wanted) == {
        "IHSP_VAULT__ROLE_ID",
        "IHSP_VAULT__SECRET_ID",
        "IHSP_BOT_VAULT__ROLE_ID",
        "IHSP_BOT_VAULT__SECRET_ID",
        "IHSP_ESSAY_VAULT__ROLE_ID",
        "IHSP_ESSAY_VAULT__SECRET_ID",
    }
    spec = importlib.util.spec_from_file_location(
        "vault_setup", MATERIALS_DIR / "vault" / "setup.py"
    )
    assert spec is not None and spec.loader is not None
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    client = MagicMock()
    approle = client.auth.approle
    approle.read_role_id.side_effect = lambda role_name: {
        "data": {"role_id": f"role-of-{role_name}"}
    }
    approle.generate_secret_id.side_effect = lambda role_name: {
        "data": {"secret_id": f"secret-of-{role_name}"}
    }
    monkeypatch.setattr(setup.hvac, "Client", lambda **_: client)
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setattr("sys.argv", ["setup.py", "--print-credentials"])

    assert setup.main() == 0

    lines = capsys.readouterr().out.splitlines()
    printed = dict(line.split("=", 1) for line in lines if "=" in line)
    assert {key: printed.get(key) for key in wanted} == {
        "IHSP_VAULT__ROLE_ID": "role-of-identity",
        "IHSP_VAULT__SECRET_ID": "secret-of-identity",
        "IHSP_BOT_VAULT__ROLE_ID": "role-of-telegram-bots",
        "IHSP_BOT_VAULT__SECRET_ID": "secret-of-telegram-bots",
        "IHSP_ESSAY_VAULT__ROLE_ID": "role-of-admission-essays",
        "IHSP_ESSAY_VAULT__SECRET_ID": "secret-of-admission-essays",
    }


def _load_vault_setup() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "vault_setup", MATERIALS_DIR / "vault" / "setup.py"
    )
    assert spec is not None and spec.loader is not None
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    return setup


def test_credentials_destroy_old_secret_ids_before_generating_a_new_one() -> None:
    setup = _load_vault_setup()
    client = MagicMock()
    approle = client.auth.approle
    approle.read_role_id.return_value = {"data": {"role_id": "r"}}
    approle.list_secret_id_accessors.return_value = {"data": {"keys": ["a1", "a2"]}}
    approle.generate_secret_id.return_value = {"data": {"secret_id": "new"}}

    assert setup.credentials(client) == ("r", "new")

    names = [call[0] for call in approle.method_calls]
    assert names.index("destroy_secret_id_accessor") < names.index("generate_secret_id")
    destroyed = [
        c.kwargs["secret_id_accessor"]
        for c in approle.destroy_secret_id_accessor.call_args_list
    ]
    assert destroyed == ["a1", "a2"]


def test_credentials_tolerate_a_role_without_secret_ids() -> None:
    setup = _load_vault_setup()
    client = MagicMock()
    approle = client.auth.approle
    approle.read_role_id.return_value = {"data": {"role_id": "r"}}
    approle.list_secret_id_accessors.side_effect = setup.InvalidPath()
    approle.generate_secret_id.return_value = {"data": {"secret_id": "new"}}

    assert setup.credentials(client) == ("r", "new")
    approle.destroy_secret_id_accessor.assert_not_called()


def test_prod_init_vault_uses_a_short_lived_token_and_revokes_old_secrets() -> None:
    script = (SCRIPTS_DIR / "prod_init.sh").read_text(encoding="utf-8")
    assert "vault token create -policy=root -ttl=15m" in script
    assert "vault token revoke -self" in script
    assert script.index("secret-id-accessor/destroy") < script.index(
        "-field=secret_id auth/approle/role/backup/secret-id"
    )


def test_predeploy_dump_is_encrypted_and_restorable() -> None:
    deploy = (SCRIPTS_DIR / "cloud_deploy.sh").read_text(encoding="utf-8")
    assert "pre-${tag}-${stamp}.dump.age" in deploy
    assert "pg_dump -U ihsp -Fc ihsp" in deploy and "-Fc hydra" in deploy
    assert "age -r" in deploy and "BACKUP_AGE_RECIPIENT" in deploy
    assert "IHSP_DEPLOY_PLAIN_DUMP" in deploy
    assert deploy.index("age -r") < deploy.index("hydra-migrate")
    assert "scripts/restore.sh $predump" in deploy
    restore = (SCRIPTS_DIR / "restore.sh").read_text(encoding="utf-8")
    assert "*.dump.age" in restore
