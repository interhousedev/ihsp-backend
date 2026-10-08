"""Container health probes that need nothing but the Python standard library.

The backend image has no curl, so compose healthchecks call this file (mounted
read-only at /healthcheck/check.py). Exit code 0 means healthy.

    check.py http <url>              GET the URL; any 2xx answer is healthy
    check.py smtp <host> <port>      connect and expect an SMTP "220" greeting
    check.py proc <token> [<token>]  a process whose argv contains every token runs
                                     (for example `proc app worker` for
                                     `python -m app worker`)
"""
import os
import sys
import urllib.request
from pathlib import Path

TIMEOUT_SECONDS = 3


def check_http(url: str) -> bool:
    """Return True when a GET of the URL answers with a 2xx status."""
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return 200 <= response.status < 300


def check_smtp(host: str, port: int) -> bool:
    """Return True when the server greets with an SMTP 220 banner."""
    import socket

    with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS) as sock:
        return sock.recv(3) == b"220"


def check_proc(tokens: list[str]) -> bool:
    """Return True when another process has every token among its arguments."""
    wanted = {token.encode() for token in tokens}
    me = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            argv = set((entry / "cmdline").read_bytes().split(b"\0"))
        except OSError:
            continue
        if wanted <= argv:
            return True
    return False


def main(argv: list[str]) -> int:
    """Run one probe; any exception counts as unhealthy."""
    kind = argv[0] if argv else ""
    try:
        if kind == "http" and len(argv) == 2:
            return 0 if check_http(argv[1]) else 1
        if kind == "smtp" and len(argv) == 3:
            return 0 if check_smtp(argv[1], int(argv[2])) else 1
        if kind == "proc" and len(argv) >= 2:
            return 0 if check_proc(argv[1:]) else 1
    except Exception:  # noqa: BLE001 - every failure means "not healthy"
        return 1
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
