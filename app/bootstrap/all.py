"""Development process: every HTTP router, MCP and public pages in one app (8000)."""

import argparse

from app.bootstrap.http_app import run_http
from app.settings import Settings


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Serve identity, API, MCP, room pages and short links until interrupted."""
    return run_http(settings, "all")
