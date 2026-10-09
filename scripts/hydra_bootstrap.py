"""Idempotent Hydra bootstrap: first-party OAuth clients and the JWT-bearer trust.

Usage (settings come from the environment, as in every process):

    IHSP_ENV_FILE=materials/dev.env uv run python scripts/hydra_bootstrap.py

Creates or updates

* the seven public PKCE clients `id`, `sp`, `staff`, `admin`, `lms`, `app`, `library`
  (consent skipped: the identity process accepts it on the server and answers Hydra's
  consent URL with a redirect, see `GET /v1/oauth/flow/consent`). `app`, the installable
  PWA, keeps people signed in longer: its refresh tokens live 90 days (2160h) instead
  of Hydra's global 720h, set per client to match its 90-day `rt_app` cookie;
* the confidential client `miniapp` (JWT-bearer grant for the Telegram mini app). Its
  secret is `IHSP_HYDRA__MINIAPP_CLIENT_SECRET`; when that is not set the script
  generates one and prints it as an env line for `.env` (first run only);
* the trust relationship for the issuer `IHSP_JWT_BEARER__ISSUER` with the public
  key of the identity signing key (replaced on every run).

Re-running changes nothing that is already correct.
"""

import os
import secrets
import sys
import time
from datetime import timedelta
from typing import Any

from app.modules.identity.domain.client_policy import (
    LONG_SESSION_CLIENTS,
    refresh_days,
)
from app.modules.identity.infrastructure.jwt_assertion import JoseAssertionSigner
from app.settings import Settings, load_settings
from app.shared.clock import SystemClock

import httpx

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
AUDIENCE = "ihsp-api"
SCOPE = "openid offline_access"
WEB_APPS = ("id", "sp", "staff", "admin", "lms", "app", "library")
# Shown on the login form ("to continue to ..."), so they read like product names.
CLIENT_NAMES = {
    "id": "IHSP Account",
    "sp": "IHSP Student Portal",
    "staff": "IHSP Staff Portal",
    "admin": "IHSP Administration",
    "lms": "IHSP Learning",
    "app": "IHSP App",
    "library": "IHSP Library",
}
MINIAPP = "miniapp"
DEV_MINIAPP_SECRET = "dev-miniapp-secret"  # default of identity's own setting
TRUST_YEARS = 2
READY_WAIT_SECONDS = 60


def out(message: str) -> None:
    """Write a line to stdout."""
    sys.stdout.write(message + "\n")


def web_client(app: str, base_url: str) -> dict[str, Any]:
    """A first-party public client: PKCE, no secret, consent skipped.

    Long-session clients (`app`) also get their own refresh token lifespans; the
    others inherit Hydra's global 720h.
    """
    base = base_url.rstrip("/")
    client: dict[str, Any] = {
        "client_id": app,
        "client_name": CLIENT_NAMES.get(app, f"IHSP {app}"),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": SCOPE,
        "audience": [AUDIENCE],
        "redirect_uris": [f"{base}/auth/callback/"],
        "post_logout_redirect_uris": [f"{base}/"],
        "skip_consent": True,
        "skip_logout_consent": True,
        "metadata": {"first_party": True},
    }
    if app in LONG_SESSION_CLIENTS:
        # Go durations have no "d" unit, so days are written as hours.
        lifespan = f"{refresh_days(app) * 24}h"
        client["authorization_code_grant_refresh_token_lifespan"] = lifespan
        client["refresh_token_grant_refresh_token_lifespan"] = lifespan
    return client


def web_app_bases(settings: Settings) -> dict[str, str]:
    """The public origin of every web app, from `IHSP_URLS__*`."""
    urls = settings.urls
    return {
        "id": urls.id,
        "sp": urls.sp,
        "staff": urls.staff,
        "admin": urls.admin,
        "lms": urls.lms,
        "app": urls.app,
        "library": urls.library,
    }


def miniapp_client(secret: str | None) -> dict[str, Any]:
    """The confidential client of the JWT-bearer grant (secret optional on update)."""
    client: dict[str, Any] = {
        "client_id": MINIAPP,
        "client_name": "IHSP Telegram mini app",
        "token_endpoint_auth_method": "client_secret_basic",
        "grant_types": [JWT_BEARER_GRANT],
        "response_types": [],
        "scope": SCOPE,
        "audience": [AUDIENCE],
        "metadata": {"first_party": True},
    }
    if secret:
        client["client_secret"] = secret
    return client


class HydraAdminApi:
    """The few admin calls the bootstrap needs."""

    def __init__(self, admin_url: str) -> None:
        """Connect to the admin API (private port)."""
        self._http = httpx.Client(base_url=admin_url.rstrip("/"), timeout=10.0)

    def wait_ready(self) -> None:
        """Wait until Hydra answers `/health/ready`."""
        deadline = time.monotonic() + READY_WAIT_SECONDS
        while True:
            try:
                if self._http.get("/health/ready").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise SystemExit("Hydra admin API is not ready")
            time.sleep(1.0)

    def upsert_client(self, client: dict[str, Any]) -> str:
        """Create the client or replace it; return `created` or `updated`."""
        client_id = client["client_id"]
        existing = self._http.get(f"/admin/clients/{client_id}")
        if existing.status_code == 404:
            self._http.post("/admin/clients", json=client).raise_for_status()
            return "created"
        existing.raise_for_status()
        self._http.put(f"/admin/clients/{client_id}", json=client).raise_for_status()
        return "updated"

    def replace_trust(self, issuer: str, grant: dict[str, Any]) -> None:
        """Delete the trust relationships of the issuer and create the new one."""
        listed = self._http.get(
            "/admin/trust/grants/jwt-bearer/issuers", params={"issuer": issuer}
        )
        listed.raise_for_status()
        for item in listed.json():
            self._http.delete(
                f"/admin/trust/grants/jwt-bearer/issuers/{item['id']}"
            ).raise_for_status()
        self._http.post(
            "/admin/trust/grants/jwt-bearer/issuers", json=grant
        ).raise_for_status()


def trust_grant(settings: Settings) -> dict[str, Any]:
    """The trust relationship for identity's assertions (public key only)."""
    signer = JoseAssertionSigner(
        private_key_pem=settings.jwt_bearer.private_key_pem.get_secret_value(),
        key_id=settings.jwt_bearer.key_id,
        issuer=settings.jwt_bearer.issuer,
        token_url="",
        clock=SystemClock(),
    )
    expires = SystemClock().now() + timedelta(days=365 * TRUST_YEARS)
    return {
        "issuer": settings.jwt_bearer.issuer,
        "allow_any_subject": True,
        "scope": SCOPE.split(),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "jwk": signer.public_jwk(),
    }


def miniapp_secret(settings: Settings) -> tuple[str | None, bool]:
    """The secret to set and whether it was generated (so it must be printed)."""
    configured = os.environ.get("IHSP_HYDRA__MINIAPP_CLIENT_SECRET")
    if configured:
        return configured, False
    if settings.env != "prod":
        return DEV_MINIAPP_SECRET, False
    return secrets.token_urlsafe(32), True


def main() -> int:
    """Run the bootstrap against the admin API of the configured Hydra."""
    settings = load_settings()
    api = HydraAdminApi(settings.hydra.admin_url)
    api.wait_ready()
    bases = web_app_bases(settings)
    for app in WEB_APPS:
        out(f"client {app}: {api.upsert_client(web_client(app, bases[app]))}")
    secret, generated = miniapp_secret(settings)
    out(f"client {MINIAPP}: {api.upsert_client(miniapp_client(secret))}")
    if generated:
        out(f"IHSP_HYDRA__MINIAPP_CLIENT_SECRET={secret}")
    if settings.jwt_bearer.ephemeral:
        out("warning: no JWT_BEARER key; the trusted key dies with this script")
    api.replace_trust(settings.jwt_bearer.issuer, trust_grant(settings))
    out(f"trust {settings.jwt_bearer.issuer}: replaced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
