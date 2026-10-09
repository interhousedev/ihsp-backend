"""The compose files and env samples speak the language of app.settings."""

import os
import re
from pathlib import Path
from typing import Any

from app.settings import Settings
from app.settings_loader import setting_exists
from tests.deploy.helpers import (
    BACKEND_PROCESSES,
    LOCAL_ENV_SAMPLE,
    MATERIALS_DIR,
    PROD_ENV_SAMPLE,
    SCRIPTS_DIR,
    requires_compose,
)

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = requires_compose

ENV_LINE = re.compile(r"^#?\s*(IHSP_[A-Z0-9_]+)=", re.MULTILINE)
# Read by identity's Hydra client (its own settings class), not by Settings.
OUTSIDE_SETTINGS = {
    "IHSP_HYDRA__MINIAPP_CLIENT_ID",
    "IHSP_HYDRA__MINIAPP_CLIENT_SECRET",
}
# The processes that read EMIS secrets and sign JWT-bearer assertions in production.
SECRET_HOLDERS = ("identity", "worker")


def _setting_exists(name: str) -> bool:
    """Return True when IHSP_<SECTION>__<FIELD> names a field of Settings.

    Dict sections such as `IHSP_AI__TASKS__<TASK>__MODEL` are checked too, including
    that the task name is a real one.
    """
    return setting_exists(name)


def _env_names(text: str) -> set[str]:
    return set(ENV_LINE.findall(text))


def _compose_env_names(model: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for service in model["services"].values():
        names |= {k for k in service.get("environment", {}) if k.startswith("IHSP_")}
    return {name for name in names if not name.startswith("IHSP_WEB_")} - {
        "IHSP_BOT_USERNAME",
        "IHSP_STORAGE_ORIGIN",
        *OUTSIDE_SETTINGS,
    }


def test_every_ihsp_variable_of_the_prod_compose_is_a_setting(
    prod_model: dict[str, Any],
) -> None:
    unknown = {n for n in _compose_env_names(prod_model) if not _setting_exists(n)}
    # Hydra's entrypoint also reads IHSP_TOKENS__SERVICE_TOKEN; it is a setting too.
    assert unknown == set()


def test_every_ihsp_variable_of_the_local_compose_is_a_setting(
    local_model: dict[str, Any],
) -> None:
    unknown = {n for n in _compose_env_names(local_model) if not _setting_exists(n)}
    assert unknown == set()


@pytest.mark.parametrize("sample", [PROD_ENV_SAMPLE, LOCAL_ENV_SAMPLE])
def test_env_samples_only_use_known_variables(sample: Path) -> None:
    text = sample.read_text(encoding="utf-8")
    unknown = {
        n
        for n in _env_names(text)
        if not _setting_exists(n)
        and not n.startswith("IHSP_WEB_")
        and n not in OUTSIDE_SETTINGS
    }
    assert unknown == set()


def test_generated_secret_list_matches_the_sample() -> None:
    sample = PROD_ENV_SAMPLE.read_text(encoding="utf-8")
    placeholders = set(re.findall(r"^(\w+)=CHANGE_ME_GENERATED$", sample, re.MULTILINE))
    script = (SCRIPTS_DIR / "prod_init.sh").read_text(encoding="utf-8")
    block = re.search(r"GENERATED=\((.*?)\n\)", script, re.DOTALL)
    assert block is not None
    assert set(block.group(1).split()) == placeholders


def _key_file(tmp_path: Path) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path = tmp_path / "jwt-bearer.pem"
    path.write_bytes(pem)
    return path


def _load(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, key: Path | None
) -> Settings:
    """Settings as the process would see them (the key file is a local stand-in)."""
    for name in [n for n in list(os.environ) if n.startswith("IHSP_")]:
        monkeypatch.delenv(name)
    for name, value in env.items():
        if name.startswith("IHSP_"):
            monkeypatch.setenv(name, value)
    if key is not None and "IHSP_JWT_BEARER__PRIVATE_KEY_PATH" in env:
        monkeypatch.setenv("IHSP_JWT_BEARER__PRIVATE_KEY_PATH", str(key))
    return Settings()


def _env(model: dict[str, Any], process: str) -> dict[str, str]:
    environment = model["services"][process]["environment"]
    return {k: v for k, v in environment.items() if v is not None}


@pytest.mark.parametrize("process", BACKEND_PROCESSES)
def test_every_prod_process_passes_the_production_guard(
    process: str,
    prod_model_after_init: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env = _env(prod_model_after_init, process)
    settings = _load(env, monkeypatch, _key_file(tmp_path))
    settings.require_production_ready(process)
    assert settings.env == "prod"
    assert settings.tokens.refresh_cookie_secure is True
    assert settings.vault.token is None
    # With the trailing slash, as in Hydra's urls.self.issuer.
    assert settings.hydra.issuer == "https://id.ihsu.uz/"
    assert settings.urls.rooms == "https://ihsu.uz/r"


@pytest.mark.parametrize("process", BACKEND_PROCESSES)
def test_only_identity_and_worker_need_the_approle_and_the_key(
    process: str,
    prod_model: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Before prod_init.sh vault ran, the secret holders refuse to start."""
    settings = _load(_env(prod_model, process), monkeypatch, _key_file(tmp_path))
    if process in SECRET_HOLDERS:
        with pytest.raises(ValueError, match="VAULT__ROLE_ID"):
            settings.require_production_ready(process)
    else:
        settings.require_production_ready(process)


@pytest.mark.parametrize("process", BACKEND_PROCESSES)
def test_every_local_process_environment_loads(
    process: str,
    local_model: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _load(_env(local_model, process), monkeypatch, _key_file(tmp_path))
    settings.require_production_ready(process)  # a no-op outside production
    assert settings.env == "dev"
    assert settings.emis.mode == "fake"
    assert settings.hydra.issuer == "http://id.localhost/"


def test_only_identity_and_worker_hold_vault_credentials(
    prod_model_after_init: dict[str, Any],
) -> None:
    for name, service in prod_model_after_init["services"].items():
        values = " ".join(str(v) for v in service.get("environment", {}).values())
        assert "backup-role" not in values and "backup-secret" not in values, name
        holds = "real-role" in values and "real-secret" in values
        assert holds == (name in SECRET_HOLDERS), name
    for name in BACKEND_PROCESSES:
        environment = prod_model_after_init["services"][name]["environment"]
        has_ids = bool(environment.get("IHSP_VAULT__ROLE_ID"))
        assert has_ids == (name in SECRET_HOLDERS), name


def test_only_identity_and_worker_mount_the_signing_key(
    prod_model: dict[str, Any],
) -> None:
    for name in BACKEND_PROCESSES:
        service = prod_model["services"][name]
        sources = {secret["source"] for secret in service.get("secrets", [])}
        assert sources == ({"jwt_bearer"} if name in SECRET_HOLDERS else set()), name
        has_path = "IHSP_JWT_BEARER__PRIVATE_KEY_PATH" in service["environment"]
        assert has_path == (name in SECRET_HOLDERS), name
    assert set(prod_model["secrets"]) == {"jwt_bearer"}


def test_the_worker_can_reach_vault(prod_model: dict[str, Any]) -> None:
    """identity.destroy_emis_secret runs in the worker: it needs the data network."""
    worker = prod_model["services"]["worker"]
    assert "data" in worker["networks"]
    assert "vault" in worker["depends_on"]
    assert worker["environment"]["IHSP_VAULT__URL"] == "http://vault:8200"


def test_the_miniapp_secret_reaches_identity_and_the_bootstrap_job(
    prod_model: dict[str, Any],
) -> None:
    for name in ("identity", "bootstrap"):
        env = prod_model["services"][name]["environment"]
        assert env["IHSP_HYDRA__MINIAPP_CLIENT_SECRET"], name


def test_vault_policy_files_exist() -> None:
    for name in ("identity.hcl", "backup.hcl"):
        assert (MATERIALS_DIR / "vault" / "policies" / name).is_file()
