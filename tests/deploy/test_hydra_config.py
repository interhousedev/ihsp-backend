"""hydra.prod.yml follows hydra.dev.yml except for environment-specific settings."""

from pathlib import Path
from typing import Any

from tests.deploy.helpers import MATERIALS_DIR

import pytest
import yaml  # type: ignore[import-untyped]

HYDRA_DIR = MATERIALS_DIR / "hydra"


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((HYDRA_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def prod() -> dict[str, Any]:
    return _load("hydra.prod.yml")


@pytest.fixture(scope="module")
def dev() -> dict[str, Any]:
    return _load("hydra.dev.yml")


@pytest.mark.parametrize(
    "section", ["strategies", "ttl", "oidc", "sqa", "log", "serve.cookies"]
)
def test_sections_that_must_match_dev(
    prod: dict[str, Any], dev: dict[str, Any], section: str
) -> None:
    def pick(model: dict[str, Any]) -> Any:
        value: Any = model
        for part in section.split("."):
            value = value[part]
        return value

    assert pick(prod) == pick(dev)


def test_oauth2_settings_match_dev_except_the_hook(
    prod: dict[str, Any], dev: dict[str, Any]
) -> None:
    prod_oauth = {k: v for k, v in prod["oauth2"].items() if k != "token_hook"}
    dev_oauth = {k: v for k, v in dev["oauth2"].items() if k != "token_hook"}
    assert prod_oauth == dev_oauth
    assert prod["oauth2"]["pkce"]["enforced_for_public_clients"] is True
    assert prod["oauth2"]["grant"]["refresh_token"]["rotation_grace_period"] == "30s"


def test_prod_urls_are_https(prod: dict[str, Any]) -> None:
    urls = prod["urls"]
    assert urls["self"]["issuer"] == "https://id.ihsu.uz/"  # MCP clients compare it
    assert urls["post_logout_redirect"] == "https://id.ihsu.uz/"
    for key in ("login", "consent", "logout"):
        assert urls[key] == f"https://api.ihsu.uz/v1/oauth/flow/{key}", key


def test_login_consent_and_logout_are_redirect_endpoints_of_identity(
    prod: dict[str, Any], dev: dict[str, Any]
) -> None:
    """ID-16: no page is rendered unless a form is needed; dev and prod use one path."""
    for key in ("login", "consent", "logout"):
        assert dev["urls"][key] == f"http://localhost:8000/v1/oauth/flow/{key}", key
        assert prod["urls"][key].endswith(f"/v1/oauth/flow/{key}"), key


def test_single_sign_on_session_can_last_thirty_days(prod: dict[str, Any]) -> None:
    """`remember_for` of the login (30 days) is capped by this lifetime."""
    assert prod["ttl"]["authentication_session"] == "8760h"


def test_prod_secrets_and_dev_mode_stay_out_of_the_file(prod: dict[str, Any]) -> None:
    assert "secrets" not in prod
    assert "dsn" not in prod
    assert "dev" not in prod


def test_durations_never_use_days(prod: dict[str, Any]) -> None:
    for name, value in prod["ttl"].items():
        assert str(value)[-1] in "smh", name


def test_token_hook_targets_identity_with_a_placeholder_secret(
    prod: dict[str, Any],
) -> None:
    hook = prod["oauth2"]["token_hook"]
    assert hook["url"] == "http://identity:8001/v1/oauth/token-hook"
    config = hook["auth"]["config"]
    assert (config["in"], config["name"]) == ("header", "Authorization")
    assert config["value"] == "Bearer REPLACE_WITH_TOKENS__SERVICE_TOKEN"


def test_client_urls_may_not_target_the_internal_network(prod: dict[str, Any]) -> None:
    http = prod["clients"]["http"]
    assert http["disallow_private_ip_ranges"] is True
    assert http["private_ip_exception_urls"] == [prod["oauth2"]["token_hook"]["url"]]


def test_dynamic_client_registration_is_on_without_offline_access(
    prod: dict[str, Any],
) -> None:
    dcr = prod["oidc"]["dynamic_client_registration"]
    assert dcr["enabled"] is True
    assert dcr["default_scope"] == ["openid"]


def test_the_compose_files_use_the_same_config_file() -> None:
    for name in ("docker-compose.prod.yaml", "docker-compose.local.yaml"):
        text = Path(MATERIALS_DIR / name).read_text(encoding="utf-8")
        assert "./hydra/hydra.prod.yml:/etc/config/hydra/hydra.yml:ro" in text


def test_compose_files_point_hydra_at_the_flow_endpoints() -> None:
    expected = {
        "docker-compose.prod.yaml": "https://api.${DOMAIN}",
        "docker-compose.local.yaml": (
            "http://api.${LOCAL_DOMAIN:-localhost}${LOCAL_PORT_SUFFIX:-}"
        ),
    }
    for name, base in expected.items():
        text = Path(MATERIALS_DIR / name).read_text(encoding="utf-8")
        for key in ("login", "consent", "logout"):
            line = f"URLS_{key.upper()}: {base}/v1/oauth/flow/{key}"
            assert line in text, (name, line)
