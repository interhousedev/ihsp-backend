"""The payloads scripts/hydra_bootstrap.py sends to Hydra (no network)."""

import importlib.util
import re
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
    """ID-16: six first-party clients, redirect to `/auth/callback/` of the app."""
    client = bootstrap.web_client("sp", "http://localhost:3002/")

    assert client["token_endpoint_auth_method"] == "none"
    assert client["skip_consent"] is True
    assert client["grant_types"] == ["authorization_code", "refresh_token"]
    assert client["redirect_uris"] == ["http://localhost:3002/auth/callback/"]
    assert client["post_logout_redirect_uris"] == ["http://localhost:3002/"]
    assert client["audience"] == ["ihsp-api"]
    assert client["scope"] == "openid offline_access"


def test_web_clients_have_names_that_read_well_on_the_login_form(
    bootstrap: ModuleType,
) -> None:
    """The form says "to continue to <name>"."""
    names = {
        app: bootstrap.web_client(app, f"http://localhost/{app}")["client_name"]
        for app in bootstrap.WEB_APPS
    }

    assert names["sp"] == "IHSP Student Portal"
    assert names["admin"] == "IHSP Administration"
    assert names["app"] == "IHSP App"
    assert len(set(names.values())) == len(names)


def test_the_installed_app_is_a_web_client_with_its_own_callback(
    bootstrap: ModuleType,
) -> None:
    """PWA-1: `app` is public PKCE, consent skipped, redirect on the app host."""
    client = bootstrap.web_client("app", "http://localhost:3007/")

    assert "app" in bootstrap.WEB_APPS
    assert client["client_id"] == "app"
    assert client["token_endpoint_auth_method"] == "none"
    assert client["skip_consent"] is True
    assert client["grant_types"] == ["authorization_code", "refresh_token"]
    assert client["redirect_uris"] == ["http://localhost:3007/auth/callback/"]
    assert client["post_logout_redirect_uris"] == ["http://localhost:3007/"]
    assert client["metadata"] == {"first_party": True}


def test_the_installed_app_keeps_its_refresh_token_for_90_days_in_hydra(
    bootstrap: ModuleType,
) -> None:
    """PWA-2: Hydra's 720h default would cut the 90-day cookie short, so set 2160h."""
    client = bootstrap.web_client("app", "http://localhost:3007")

    assert client["authorization_code_grant_refresh_token_lifespan"] == "2160h"
    assert client["refresh_token_grant_refresh_token_lifespan"] == "2160h"


@pytest.mark.parametrize("app", ["id", "sp", "staff", "admin", "lms", "library"])
def test_the_websites_inherit_the_global_refresh_lifespan(
    bootstrap: ModuleType, app: str
) -> None:
    """PWA-2: no per-client lifespan keys, so Hydra's global 720h applies."""
    client = bootstrap.web_client(app, f"http://localhost/{app}")

    assert not [key for key in client if key.endswith("refresh_token_lifespan")]


def test_the_library_is_a_web_client_with_its_own_callback(
    bootstrap: ModuleType,
) -> None:
    """LIB-1: `library` is public PKCE, consent skipped, redirect on its host."""
    client = bootstrap.web_client("library", "http://localhost:3008/")

    assert "library" in bootstrap.WEB_APPS
    assert client["client_id"] == "library"
    assert client["client_name"] == "IHSP Library"
    assert client["token_endpoint_auth_method"] == "none"
    assert client["skip_consent"] is True
    assert client["grant_types"] == ["authorization_code", "refresh_token"]
    assert client["redirect_uris"] == ["http://localhost:3008/auth/callback/"]
    assert client["post_logout_redirect_uris"] == ["http://localhost:3008/"]
    assert client["metadata"] == {"first_party": True}


def test_hydra_lifespans_are_go_durations_in_hours(bootstrap: ModuleType) -> None:
    """Go's parser has no "d" unit, so 90 days are written as 2160h."""
    client = bootstrap.web_client("app", "http://localhost:3007")

    lifespans = [v for k, v in client.items() if k.endswith("refresh_token_lifespan")]

    assert len(lifespans) == 2
    assert all(re.fullmatch(r"[1-9][0-9]*h", value) for value in lifespans)


def test_every_web_app_has_a_base_url_from_the_settings(
    bootstrap: ModuleType,
) -> None:
    """PWA-1: a client without a base URL would crash the bootstrap midway."""
    settings = Settings(env="test")

    bases = bootstrap.web_app_bases(settings)

    assert set(bases) == set(bootstrap.WEB_APPS)
    assert bases["app"] == settings.urls.app == "http://localhost:3007"
    assert bases["sp"] == settings.urls.sp
    assert bases["library"] == settings.urls.library == "http://localhost:3008"


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
