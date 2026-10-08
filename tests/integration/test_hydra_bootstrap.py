"""The payloads scripts/hydra_bootstrap.py sends to Hydra (no network)."""

import importlib.util
from pathlib import Path
from types import ModuleType

from app.settings import Settings

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hydra_bootstrap.py"


@pytest.fixture(scope="module")
def bootstrap() -> ModuleType:
    """Load the script as a module."""
    spec = importlib.util.spec_from_file_location("hydra_bootstrap", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_web_clients_are_public_pkce_clients_without_consent(
    bootstrap: ModuleType,
) -> None:
    """ID-16: five first-party clients, redirect to `/auth/callback/` of the app."""
    client = bootstrap.web_client("sp", "http://localhost:3002/")

    assert client["token_endpoint_auth_method"] == "none"
    assert client["skip_consent"] is True
    assert client["grant_types"] == ["authorization_code", "refresh_token"]
    assert client["redirect_uris"] == ["http://localhost:3002/auth/callback/"]
    assert client["post_logout_redirect_uris"] == ["http://localhost:3002/"]
    assert client["audience"] == ["ihsp-api"]
    assert client["scope"] == "openid offline_access"


def test_miniapp_client_is_confidential_with_the_jwt_bearer_grant(
    bootstrap: ModuleType,
) -> None:
    """The mini app redeems our signed assertions with a client secret."""
    client = bootstrap.miniapp_client("s3cret")

    assert client["grant_types"] == [bootstrap.JWT_BEARER_GRANT]
    assert client["token_endpoint_auth_method"] == "client_secret_basic"
    assert client["client_secret"] == "s3cret"
    assert "client_secret" not in bootstrap.miniapp_client(None)


def test_trust_grant_carries_only_the_public_key(bootstrap: ModuleType) -> None:
    """The trust relationship names our issuer and a public RS256 key."""
    settings = Settings(env="test")

    grant = bootstrap.trust_grant(settings)

    assert grant["issuer"] == settings.jwt_bearer.issuer
    assert grant["jwk"]["kid"] == settings.jwt_bearer.key_id
    assert grant["jwk"]["alg"] == "RS256"
    assert "d" not in grant["jwk"]
    assert grant["allow_any_subject"] is True
