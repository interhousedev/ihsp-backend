"""Structure of the production and local compose files (`docker compose config`)."""

import subprocess
from pathlib import Path
from typing import Any

from tests.deploy.helpers import (
    LOCAL_COMPOSE,
    MATERIALS_DIR,
    PROD_COMPOSE,
    PROD_ENV_SAMPLE,
    compose_json,
    is_one_shot,
    published_ports,
    requires_compose,
)

import pytest

pytestmark = requires_compose

COMMON_SERVICES = {
    "postgres",
    "redis",
    "vault",
    "s3",
    "hydra-migrate",
    "hydra",
    "migrate",
    "identity",
    "api",
    "bot",
    "mail",
    "worker",
    "scheduler",
    "web",
    "nginx",
    "bootstrap",
}
PROD_ONLY_SERVICES = {"hydra-janitor", "certbot", "vault-setup", "s3-init"}
LOCAL_ONLY_SERVICES = {"mailpit", "vault-init", "s3-init"}
# Hydra's admin API and Vault must never be reachable from outside the Docker networks.
FORBIDDEN_PUBLISHED_PORTS = {4445, 8200, 8201, 5432, 6379}


def _model(request: pytest.FixtureRequest, which: str) -> dict[str, Any]:
    model: dict[str, Any] = request.getfixturevalue(f"{which}_model")
    return model


@pytest.mark.parametrize(
    ("compose_file", "env_file"),
    [(PROD_COMPOSE, PROD_ENV_SAMPLE), (LOCAL_COMPOSE, None)],
    ids=["prod", "local"],
)
def test_compose_config_is_valid(compose_file: Path, env_file: Path | None) -> None:
    command = ["docker", "compose"]
    if env_file is not None:
        command += ["--env-file", str(env_file)]
    command += ["-f", str(compose_file), "--profile", "*", "config", "-q"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_prod_compose_without_env_file_demands_the_secrets() -> None:
    result = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "-f", str(PROD_COMPOSE)]
        + ["config", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "required variable" in result.stderr


def test_prod_has_every_process_and_job(prod_model: dict[str, Any]) -> None:
    assert (COMMON_SERVICES | PROD_ONLY_SERVICES) <= set(prod_model["services"])


def test_local_has_every_process_and_job(local_model: dict[str, Any]) -> None:
    assert (COMMON_SERVICES | LOCAL_ONLY_SERVICES) <= set(local_model["services"])


@pytest.mark.parametrize("which", ["prod", "local"])
def test_every_service_has_a_healthcheck_or_is_one_shot(
    request: pytest.FixtureRequest, which: str
) -> None:
    missing = [
        name
        for name, service in _model(request, which)["services"].items()
        if not is_one_shot(service) and not service.get("healthcheck", {}).get("test")
    ]
    assert missing == []


@pytest.mark.parametrize("which", ["prod", "local"])
def test_one_shot_jobs_are_not_restarted(
    request: pytest.FixtureRequest, which: str
) -> None:
    services = _model(request, which)["services"]
    for name in ("migrate", "hydra-migrate", "bootstrap", "s3-init"):
        assert services[name]["restart"] == "no", name


def test_prod_long_running_services_restart_unless_stopped(
    prod_model: dict[str, Any],
) -> None:
    wrong = {
        name: service.get("restart")
        for name, service in prod_model["services"].items()
        if not is_one_shot(service)
        and not service.get("profiles")
        and service.get("restart") != "unless-stopped"
    }
    assert wrong == {}


def test_prod_publishes_only_http_https_and_smtp(prod_model: dict[str, Any]) -> None:
    ports = {(name, published) for name, published, _ in published_ports(prod_model)}
    assert ports == {("nginx", 80), ("nginx", 443), ("mail", 25)}


def test_prod_publishes_no_admin_vault_or_data_store_port(
    prod_model: dict[str, Any],
) -> None:
    for name, published, target in published_ports(prod_model):
        assert published not in FORBIDDEN_PUBLISHED_PORTS, name
        assert target not in FORBIDDEN_PUBLISHED_PORTS, name
    for name in ("hydra", "hydra-migrate", "vault", "postgres", "redis", "s3"):
        assert not prod_model["services"][name].get("ports"), name


def test_prod_data_stores_sit_on_the_internal_network_only(
    prod_model: dict[str, Any],
) -> None:
    assert prod_model["networks"]["data"]["internal"] is True
    for name in ("postgres", "redis", "vault", "hydra-migrate", "hydra-janitor"):
        assert set(prod_model["services"][name]["networks"]) == {"data"}, name


def test_prod_nginx_has_a_fixed_address_on_the_edge_network(
    prod_model: dict[str, Any],
) -> None:
    edge = prod_model["services"]["nginx"]["networks"]["edge"]
    assert edge["ipv4_address"] == "172.31.240.10"
    for process in ("identity", "api"):
        env = prod_model["services"][process]["environment"]
        assert env["FORWARDED_ALLOW_IPS"] == edge["ipv4_address"]


def test_prod_images_are_pinned(prod_model: dict[str, Any]) -> None:
    images = {name: s["image"] for name, s in prod_model["services"].items()}
    assert images["hydra"] == "oryd/hydra:v26.2.0"
    assert images["s3"] == "rustfs/rustfs:1.0.1"
    assert images["vault"].startswith("hashicorp/vault:2.")
    assert images["postgres"] == "postgres:16"
    for name in ("identity", "api", "bot", "mail", "worker", "scheduler", "migrate"):
        assert images[name].startswith("ghcr.io/")
        assert images[name].endswith("/ihsp-backend:CHANGE_ME")
    assert images["web"].endswith("/ihsp-web:CHANGE_ME")


@pytest.mark.parametrize("compose_file", [PROD_COMPOSE, LOCAL_COMPOSE])
def test_minio_is_gone(compose_file: Path) -> None:
    text = compose_file.read_text(encoding="utf-8").lower()
    assert "minio/" not in text
    assert "image: quay.io/minio" not in text


def test_prod_vault_runs_in_server_mode_with_raft(prod_model: dict[str, Any]) -> None:
    vault = prod_model["services"]["vault"]
    assert vault["command"] == ["server"]
    env = vault.get("environment", {})
    assert not any(key.startswith("VAULT_DEV") for key in env)
    config = (MATERIALS_DIR / "vault" / "config" / "vault.hcl").read_text()
    assert 'storage "raft"' in config
    assert "disable_mlock = true" in config


def test_local_vault_is_in_dev_mode(local_model: dict[str, Any]) -> None:
    env = local_model["services"]["vault"]["environment"]
    assert env["VAULT_DEV_ROOT_TOKEN_ID"] == "dev-root"


def test_local_host_ports_are_loopback_only_except_the_web_edge(
    local_model: dict[str, Any],
) -> None:
    for name, service in local_model["services"].items():
        for port in service.get("ports", []):
            if name == "nginx":
                assert int(port["target"]) == 80
            else:
                assert port["host_ip"] == "127.0.0.1", name


def test_local_does_not_publish_hydra_admin(local_model: dict[str, Any]) -> None:
    for name, published, target in published_ports(local_model):
        assert 4445 not in (published, target), name


def test_local_uses_the_bundled_services(local_model: dict[str, Any]) -> None:
    services = local_model["services"]
    assert services["s3"]["image"] == "rustfs/rustfs:1.0.1"
    assert "mailpit" in services["identity"]["environment"]["IHSP_SMTP_OUT__HOST"]
    assert services["identity"]["environment"]["IHSP_EMIS__MODE"] == "fake"
    assert services["identity"]["environment"]["IHSP_OPENROUTER__MODE"] == "fake"
    assert services["identity"]["environment"]["IHSP_TELEGRAM__MODE"] == "fake"


def test_hydra_janitor_follows_the_plan(prod_model: dict[str, Any]) -> None:
    command = " ".join(prod_model["services"]["hydra-janitor"]["command"])
    for part in (
        "janitor",
        "--tokens",
        "--requests",
        "--grants",
        "--keep-if-younger 24h",
        "sleep 21600",
    ):
        assert part in command


def test_hydra_hook_secret_is_spliced_from_the_environment(
    prod_model: dict[str, Any],
) -> None:
    hydra = prod_model["services"]["hydra"]
    assert "REPLACE_WITH_TOKENS__SERVICE_TOKEN" in hydra["command"][0]
    assert hydra["environment"]["IHSP_TOKENS__SERVICE_TOKEN"]
    hydra_yml = (MATERIALS_DIR / "hydra" / "hydra.prod.yml").read_text()
    assert "REPLACE_WITH_TOKENS__SERVICE_TOKEN" in hydra_yml


def test_prod_web_csp_allows_the_api_and_the_storage_origin(
    prod_model: dict[str, Any],
) -> None:
    env = prod_model["services"]["web"]["environment"]
    assert "https://api.ihsu.uz" in env["CSP_CONNECT_SRC"]
    assert env["CSP_CONNECT_SRC"].startswith("'self'")
    assert env["IHSP_STORAGE_ORIGIN"] in env["CSP_CONNECT_SRC"]
    assert env["IHSP_STORAGE_ORIGIN"] in env["CSP_IMG_SRC"]


def test_local_web_csp_allows_the_plain_http_api_and_storage(
    local_model: dict[str, Any],
) -> None:
    env = local_model["services"]["web"]["environment"]
    assert "http://api.localhost" in env["CSP_CONNECT_SRC"]
    assert "http://localhost:9100" in env["CSP_CONNECT_SRC"]
    assert "http://localhost:9100" in env["CSP_IMG_SRC"]
    assert env["APP_ENV"] == "dev"


def test_local_web_image_is_packed_from_the_host_build_by_default(
    local_model: dict[str, Any],
) -> None:
    build = local_model["services"]["web"]["build"]
    assert build["dockerfile"] == "deploy/Dockerfile.prebuilt"
    assert build["context"].endswith("/web")


def test_local_web_image_can_be_built_in_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_DOCKERFILE", "deploy/Dockerfile")
    model = compose_json(LOCAL_COMPOSE)
    assert model["services"]["web"]["build"]["dockerfile"] == "deploy/Dockerfile"


def test_local_worker_runs_one_child_process(local_model: dict[str, Any]) -> None:
    command = local_model["services"]["worker"]["command"]
    assert command[-2:] == ["--workers", "1"]


def test_the_worker_has_its_own_vault_dependency_in_prod(
    prod_model: dict[str, Any],
) -> None:
    assert "vault" in prod_model["services"]["worker"]["depends_on"]
