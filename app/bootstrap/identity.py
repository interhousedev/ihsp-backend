"""The identity process: login app, token handler, EMIS gateway (port 8001)."""

import argparse

from app.bootstrap.http_app import run_http
from app.settings import Settings


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Serve `/v1/id/*`, `/v1/oauth/*`, `/v1/admin/users*` and `/internal/emis/*`."""
    return run_http(settings, "identity")
