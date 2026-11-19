"""Import exemplar essays from a JSON file as drafts through the admission API.

The token comes from the environment variable named by --token-env; only counts
are printed, never essay text or the token.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CHUNK = 50
PATH = "/v1/admission/staff/exemplars/import"


def _post(url: str, token: str, items: list[Any]) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - URL comes from --api
        url,
        data=json.dumps({"items": items}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "iht-exemplar-seed",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        result: dict[str, Any] = json.load(response)
    return result


def main() -> int:
    """Send the file in chunks of 50 and print created, duplicates, failed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="base URL, e.g. https://host")
    parser.add_argument("--token-env", default="IHSP_CATALOG_TOKEN")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    items: list[Any] = json.loads(args.file.read_text(encoding="utf-8"))
    chunks = [items[i : i + CHUNK] for i in range(0, len(items), CHUNK)]
    if args.dry_run:
        print(f"items={len(items)} chunks={len(chunks)}")
        return 0
    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"{args.token_env} is empty", file=sys.stderr)
        return 2
    created = duplicates = failed = 0
    for chunk in chunks:
        try:
            result = _post(args.api.rstrip("/") + PATH, token, chunk)
        except urllib.error.HTTPError as exc:
            failed += len(chunk)
            print(f"chunk failed: HTTP {exc.code}", file=sys.stderr)
            continue
        created += len(result.get("created", []))
        duplicates += len(result.get("duplicates", []))
    print(f"created={created} duplicates={duplicates} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
