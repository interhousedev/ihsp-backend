"""Settings: defaults, environment, files, production guard."""

from pathlib import Path
from typing import Any

from app.settings import Settings, load_settings
from app.settings_loader import path_exists
from app.shared.paths import BACKEND_ROOT

import pytest
from pydantic import BaseModel
from pydantic_settings import BaseSettings

MATERIALS = BACKEND_ROOT / "materials"
PEM = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"


def env_names(path: Path) -> list[str]:
    """Variable names in an env file, commented ones included."""
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("#").strip()
        name, sep, _ = line.partition("=")
        if sep and name.startswith("IHSP_") and " " not in name:
            names.append(name)
    return names


def has_field(model: type[BaseModel] | type[BaseSettings], parts: list[str]) -> bool:
    """True if the path parts name a field, walking nested models and dict keys."""
    return path_exists(parts, model)


def test_defaults_match_the_dev_compose_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 3.2: development defaults point at the compose ports."""
    monkeypatch.delenv("IHSP_ENV")  # conftest sets "test" for the whole run
    settings = Settings()

    assert settings.env == "dev"
    assert settings.database.url == "postgresql+asyncpg://ihsp:ihsp@localhost:5433/ihsp"
    assert settings.redis.url == "redis://localhost:6380/0"
    assert settings.s3.bucket == "ihsp-dev"
    assert settings.hydra.issuer == "http://localhost:4444/"
    assert settings.emis.mode == "fake"
    assert settings.limits.attendance_edit_days == 7


def test_environment_overrides_nested_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """IHSP_<SECTION>__<FIELD> sets one field."""
    monkeypatch.setenv("IHSP_DATABASE__POOL_SIZE", "3")
    monkeypatch.setenv("IHSP_TELEGRAM__ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("IHSP_VAULT__VERIFY", "false")

    settings = Settings()

    assert settings.database.pool_size == 3
    assert settings.telegram.admin_chat_id == 42
    assert settings.vault.verify is False


def test_secrets_are_masked_in_repr() -> None:
    """SecretStr keeps tokens out of logs."""
    text = repr(Settings())

    assert "dev-service-token" not in text
    assert "minio12345" not in text


def test_cors_origins_come_from_urls() -> None:
    """cors_app_origins: id, sp, staff, admin, lms, app, library; share is separate."""
    settings = Settings()

    assert settings.cors_app_origins() == [
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://localhost:3005",
        "http://localhost:3007",
        "http://localhost:3008",
    ]
    assert settings.cors_share_origins() == ["http://localhost:3006"]


def test_the_jwt_key_is_generated_in_dev_and_stable_per_process() -> None:
    """Dev and test need no key file; every Settings of a process shares one key."""
    first = Settings().jwt_bearer.private_key_pem.get_secret_value()
    second = Settings().jwt_bearer.private_key_pem.get_secret_value()

    assert first.startswith("-----BEGIN PRIVATE KEY-----")
    assert first == second


def test_the_jwt_key_is_read_from_a_file(tmp_path: Path) -> None:
    """IHSP_JWT_BEARER__PRIVATE_KEY_PATH points at the key scripts/dev.sh generates."""
    key = tmp_path / "key.pem"
    key.write_text(PEM, encoding="utf-8")

    jwt = {"private_key_path": str(key)}

    settings = Settings(jwt_bearer=jwt)  # type: ignore[arg-type]

    assert settings.jwt_bearer.private_key_pem.get_secret_value() == PEM


def test_production_refuses_development_defaults() -> None:
    """GEN-8: prod needs real secrets."""
    with pytest.raises(ValueError, match="TOKENS__SERVICE_TOKEN"):
        Settings(env="prod")


def test_production_accepts_explicit_secrets() -> None:
    """A fully configured prod passes and drops the dev Vault token for AppRole."""
    settings = Settings(
        env="prod",
        tokens={  # type: ignore[arg-type]
            "service_token": "x" * 40,
            "refresh_cookie_secure": True,
        },
        jwt_bearer={"private_key_pem": PEM},  # type: ignore[arg-type]
        s3={"secret_key": "y" * 30},  # type: ignore[arg-type]
        vault={"role_id": "r", "secret_id": "s"},  # type: ignore[arg-type]
    )

    assert settings.vault.token is None


def prod_settings(**extra: Any) -> Settings:
    """Production settings with the secrets every process shares."""
    return Settings(
        env="prod",
        tokens={  # type: ignore[arg-type]
            "service_token": "x" * 40,
            "refresh_cookie_secure": True,
        },
        s3={"secret_key": "y" * 30},  # type: ignore[arg-type]
        **extra,
    )


@pytest.mark.parametrize("process", ["api", "bot", "mail", "scheduler", "migrate"])
def test_production_needs_no_vault_or_signing_key_outside_identity_and_worker(
    process: str,
) -> None:
    """Only identity and worker hold the AppRole and the JWT-bearer key."""
    settings = prod_settings()

    settings.require_production_ready(process)

    assert settings.vault.token is None  # the dev token is dropped in production


@pytest.mark.parametrize("process", ["identity", "worker", "create-user"])
def test_production_demands_the_approle_and_key_for_the_secret_holders(
    process: str,
) -> None:
    """A missing AppRole or an in-memory key stops identity and worker at start."""
    with pytest.raises(ValueError, match=r"VAULT__ROLE_ID.*JWT_BEARER__PRIVATE_KEY"):
        prod_settings().require_production_ready(process)

    only_vault = prod_settings(vault={"role_id": "r", "secret_id": "s"})
    with pytest.raises(ValueError, match="JWT_BEARER__PRIVATE_KEY"):
        only_vault.require_production_ready(process)

    ready = prod_settings(
        vault={"role_id": "r", "secret_id": "s"}, jwt_bearer={"private_key_pem": PEM}
    )
    ready.require_production_ready(process)


def test_the_cli_checks_the_process_before_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python -m app identity` in production fails fast without the AppRole."""
    from app import __main__ as cli

    monkeypatch.setenv("IHSP_ENV", "prod")
    monkeypatch.setenv("IHSP_TOKENS__SERVICE_TOKEN", "x" * 40)
    monkeypatch.setenv("IHSP_TOKENS__REFRESH_COOKIE_SECURE", "true")
    monkeypatch.setenv("IHSP_S3__SECRET_KEY", "y" * 30)

    with pytest.raises(ValueError, match="missing for identity"):
        cli.main(["identity"])


@pytest.mark.parametrize("name", ["dev.env", ".env.sample"])
def test_every_variable_in_the_env_files_is_a_real_setting(name: str) -> None:
    """materials/.env.sample documents every variable; dev.env has no typos."""
    for variable in env_names(MATERIALS / name):
        parts = variable.removeprefix("IHSP_").lower().split("__")
        if parts == ["env_file"]:
            continue
        assert has_field(Settings, parts), variable


def test_the_sample_documents_every_setting() -> None:
    """No setting is missing from .env.sample.

    A per-task dict (`ai.tasks`) counts as documented when any of its variables is.
    """
    documented = {
        v.removeprefix("IHSP_").lower() for v in env_names(MATERIALS / ".env.sample")
    }

    def is_documented(path: str) -> bool:
        return any(name == path or name.startswith(f"{path}__") for name in documented)

    missing = []
    for section, field in Settings.model_fields.items():
        annotation: Any = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            missing += [
                f"{section}__{name}"
                for name in annotation.model_fields
                if not is_documented(f"{section}__{name}")
            ]
        elif section not in documented:
            missing.append(section)

    assert missing == []


def test_dev_env_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """IHSP_ENV_FILE=materials/dev.env builds valid Settings."""
    key = tmp_path / "jwt.pem"
    key.write_text(PEM, encoding="utf-8")
    monkeypatch.setenv("IHSP_ENV_FILE", str(MATERIALS / "dev.env"))
    monkeypatch.setenv("IHSP_JWT_BEARER__PRIVATE_KEY_PATH", str(key))

    settings = load_settings()

    assert settings.s3.endpoint_url == "http://localhost:9000"
    assert settings.tokens.service_token.get_secret_value() == "dev-service-token"
    assert settings.jwt_bearer.private_key_pem.get_secret_value() == PEM
