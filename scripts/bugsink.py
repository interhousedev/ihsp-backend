"""Triage helper for the Bugsink error tracker (canonical REST API, stdlib only).

Usage:

Set IHSP_BUGSINK_URL and IHSP_BUGSINK_TOKEN, then run one of:

    uv run python scripts/bugsink.py list [--project ID]
    uv run python scripts/bugsink.py show ISSUE_ID
    uv run python scripts/bugsink.py resolve ISSUE_ID

`list` prints the open (neither resolved nor muted) issues; `show` prints the issue
and its latest event (stacktrace, tags, request); `resolve` marks an issue resolved.
The token needs `issues:read`, `events:read` (and `projects:read` when no project is
given) and, for `resolve`, `issues:triage`. The token is never printed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

API = "/api/canonical/0"
MAX_PAGES = 20


class BugsinkError(Exception):
    """A configuration problem or a failed API call."""


class Client:
    """A minimal bearer-token client of the Bugsink canonical API."""

    def __init__(self, base_url: str, token: str) -> None:
        """Remember the instance URL and the secret token."""
        self._base = base_url.rstrip("/")
        self._token = token

    def request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Call one endpoint and return its decoded JSON (None for no content)."""
        url = path if path.startswith("http") else f"{self._base}{API}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "ihsp-bugsink-triage/1.0")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            raise BugsinkError(f"{method} {path}: HTTP {error.code} {detail}") from None
        except urllib.error.URLError as error:
            raise BugsinkError(f"{method} {path}: {error.reason}") from None
        return json.loads(raw) if raw else None

    def pages(self, path: str, query: dict[str, str]) -> Iterator[dict[str, Any]]:
        """Yield every item of a cursor-paginated list."""
        page = self.request("GET", path, query)
        for _ in range(MAX_PAGES):
            yield from page.get("results", [])
            if not page.get("next"):
                return
            page = self.request("GET", page["next"])


def project_ids(client: Client, project: str | None) -> list[str]:
    """The given project, or every project the token may list."""
    if project:
        return [project]
    return [str(item["id"]) for item in client.pages("/projects/", {})]


def open_issues(client: Client, project: str | None) -> list[dict[str, Any]]:
    """Issues that are neither resolved nor muted."""
    issues: list[dict[str, Any]] = []
    for project_id in project_ids(client, project):
        for issue in client.pages("/issues/", {"project": project_id}):
            if not issue.get("is_resolved") and not issue.get("is_muted"):
                issues.append(issue)
    return issues


def format_issue_line(issue: dict[str, Any]) -> str:
    """One line per issue for `list`."""
    title = f"{issue.get('calculated_type', '')}: {issue.get('calculated_value', '')}"
    return (
        f"{issue['id']}  events={issue.get('digested_event_count', '?')}  "
        f"last={issue.get('last_seen', '?')}  {title.strip(': ')}"
    )


def latest_event(client: Client, issue_id: str) -> dict[str, Any] | None:
    """The most recent event of an issue, in full."""
    events = list(client.pages("/events/", {"issue": issue_id, "order": "desc"}))
    if not events:
        return None
    newest = max(events, key=lambda e: str(e.get("timestamp", "")))
    event: dict[str, Any] = client.request("GET", f"/events/{newest['id']}/")
    return event


def format_event(event: dict[str, Any]) -> str:
    """Stacktrace, tags and request of one event as text."""
    data = event.get("data") or {}
    lines = [f"event {event['id']}  at {event.get('timestamp', '?')}"]
    tags = data.get("tags")
    if tags:
        pairs = tags.items() if isinstance(tags, dict) else tags
        lines.append("tags: " + ", ".join(f"{k}={v}" for k, v in pairs))
    request = data.get("request") or {}
    if request:
        lines.append(f"request: {request.get('method', '')} {request.get('url', '')}")
    lines.append("")
    lines.append(event.get("stacktrace_md") or "(no stacktrace)")
    return "\n".join(lines)


def cmd_list(client: Client, args: argparse.Namespace) -> int:
    """Print open issues."""
    issues = open_issues(client, args.project)
    for issue in issues:
        print(format_issue_line(issue))
    if not issues:
        print("no open issues")
    return 0


def cmd_show(client: Client, args: argparse.Namespace) -> int:
    """Print an issue and its latest event."""
    issue = client.request("GET", f"/issues/{args.issue}/")
    print(format_issue_line(issue))
    event = latest_event(client, args.issue)
    print()
    print(format_event(event) if event else "no events")
    return 0


def cmd_resolve(client: Client, args: argparse.Namespace) -> int:
    """Mark an issue resolved."""
    client.request("POST", f"/issues/{args.issue}/resolve/", body={})
    print(f"resolved {args.issue}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The command line."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="open issues")
    listing.add_argument("--project", default=os.environ.get("IHSP_BUGSINK_PROJECT"))
    listing.set_defaults(run=cmd_list)
    show = sub.add_parser("show", help="an issue and its latest event")
    show.add_argument("issue")
    show.set_defaults(run=cmd_show)
    resolve = sub.add_parser("resolve", help="resolve an issue")
    resolve.add_argument("issue")
    resolve.set_defaults(run=cmd_resolve)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command; the exit code is 1 on a configuration or API failure."""
    args = build_parser().parse_args(argv)
    url = os.environ.get("IHSP_BUGSINK_URL")
    token = os.environ.get("IHSP_BUGSINK_TOKEN")
    if not url or not token:
        print("set IHSP_BUGSINK_URL and IHSP_BUGSINK_TOKEN", file=sys.stderr)
        return 1
    try:
        return int(args.run(Client(url, token), args))
    except BugsinkError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
