"""The API process: every other `/v1/*` route, MCP, short links, room pages (8000)."""

import argparse

from app.bootstrap.http_app import run_http
from app.settings import Settings


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Serve the API until interrupted."""
    return run_http(settings, "api")
