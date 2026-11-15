"""scripts/bugsink.py against a fake Bugsink HTTP server."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bugsink.py"
TOKEN = "secret-token-123"
CALLS: list[tuple[str, str, str | None]] = []


class Fake(BaseHTTPRequestHandler):
    """Canonical API subset, two list pages for issues."""

    def log_message(self, *args: object) -> None:  # silence
        return

    def _send(self, payload: object) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _route(self, method: str) -> None:
        CALLS.append((method, self.path, self.headers.get("Authorization")))
        host = f"http://{self.headers['Host']}"
        path = self.path
        if path.startswith("/api/canonical/0/issues/?project=p1&page=2"):
            self._send(
                {
                    "next": None,
                    "results": [
                        {"id": "i2", "is_resolved": True, "is_muted": False},
                        {"id": "i3", "calculated_type": "B", "is_resolved": False},
                    ],
                }
            )
        elif path.startswith("/api/canonical/0/issues/?project=p1"):
            self._send(
                {
                    "next": f"{host}/api/canonical/0/issues/?project=p1&page=2",
                    "results": [
                        {
                            "id": "i1",
                            "calculated_type": "EmisUnavailable",
                            "calculated_value": "boom",
                            "digested_event_count": 11,
                        }
                    ],
                }
            )
        elif path == "/api/canonical/0/issues/i1/":
            self._send({"id": "i1", "calculated_type": "EmisUnavailable"})
        elif path.startswith("/api/canonical/0/events/?issue=i1"):
            self._send(
                {
                    "next": None,
                    "results": [
                        {"id": "e1", "timestamp": "2026-01-01T00:00:00Z"},
                        {"id": "e2", "timestamp": "2026-02-01T00:00:00Z"},
                    ],
                }
            )
        elif path == "/api/canonical/0/events/e2/":
            self._send(
                {
                    "id": "e2",
                    "timestamp": "2026-02-01T00:00:00Z",
                    "stacktrace_md": "TRACE-LINE",
                    "data": {
                        "tags": {"route": "/v1/me/honours"},
                        "request": {"method": "GET", "url": "http://x/v1/me/honours"},
                    },
                }
            )
        elif method == "POST" and path == "/api/canonical/0/issues/i1/resolve/":
            self._send({"ok": True})
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._route("POST")


@pytest.fixture
def bugsink(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The script module pointed at a fake server."""
    CALLS.clear()
    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("IHSP_BUGSINK_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("IHSP_BUGSINK_TOKEN", TOKEN)
    spec = importlib.util.spec_from_file_location("bugsink_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    server.shutdown()


def test_list_prints_open_issues_across_pages(
    bugsink: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """Resolved issues are skipped; the token goes in the header, never in output."""
    assert bugsink.main(["list", "--project", "p1"]) == 0

    out = capsys.readouterr()
    assert "i1" in out.out and "i3" in out.out and "i2" not in out.out
    assert TOKEN not in out.out + out.err
    assert all(call[2] == f"Bearer {TOKEN}" for call in CALLS)


def test_show_prints_the_latest_event(
    bugsink: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stacktrace, tags and request of the newest event."""
    assert bugsink.main(["show", "i1"]) == 0

    out = capsys.readouterr().out
    assert "TRACE-LINE" in out
    assert "route=/v1/me/honours" in out
    assert "GET http://x/v1/me/honours" in out
    assert "e1" not in out


def test_resolve_posts_to_the_issue(
    bugsink: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """POST .../resolve/."""
    assert bugsink.main(["resolve", "i1"]) == 0

    assert ("POST", "/api/canonical/0/issues/i1/resolve/", f"Bearer {TOKEN}") in CALLS
    assert "resolved i1" in capsys.readouterr().out


def test_missing_env_fails(
    bugsink: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No token: exit 1."""
    monkeypatch.delenv("IHSP_BUGSINK_TOKEN")

    assert bugsink.main(["list"]) == 1
    assert "IHSP_BUGSINK_TOKEN" in capsys.readouterr().err
