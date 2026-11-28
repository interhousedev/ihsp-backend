"""Push the seed country facts and institutions to an API with a write token.

Reads `IHSP_CATALOG_PUSH_TOKEN` (a personal token with the only scope
`admission:catalog-write`) and `IHSP_CATALOG_PUSH_URL` (the API origin, e.g.
`https://api.example.org`) from the environment or the `IHSP_ENV_FILE` file.

    uv run python scripts/push_catalog.py [--dry-run] [--only countries|institutions]
"""

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.admission.domain.catalog_push import (  # noqa: E402
    COUNTRY_BATCH_MAX,
    INSTITUTION_BATCH_MAX,
)
from app.modules.admission.infrastructure.catalog_data import load_seed  # noqa: E402

COUNTRIES = (
    ROOT
    / "app/modules/admission/infrastructure/catalog_data/countries/country_facts.json"
)
PATHS = {
    "countries": "/v1/admission/staff/catalog/push/countries",
    "institutions": "/v1/admission/staff/catalog/push/institutions",
}


def _env_file() -> dict[str, str]:
    path = os.environ.get("IHSP_ENV_FILE")
    out: dict[str, str] = {}
    if not path or not Path(path).is_file():
        return out
    for line in Path(path).read_text("utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            out[key.strip()] = value.strip().strip("'\"")
    return out


def _setting(name: str, file: dict[str, str]) -> str:
    value = os.environ.get(name) or file.get(name, "")
    if not value:
        sys.exit(f"{name} is not set (environment or IHSP_ENV_FILE)")
    return value


def _batches(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _payloads(only: str | None) -> dict[str, tuple[list[dict[str, Any]], int]]:
    out: dict[str, tuple[list[dict[str, Any]], int]] = {}
    if only in (None, "countries"):
        data = json.loads(COUNTRIES.read_text("utf-8"))
        out["countries"] = (data["countries"], COUNTRY_BATCH_MAX)
    if only in (None, "institutions"):
        out["institutions"] = (load_seed(), INSTITUTION_BATCH_MAX)
    return out


def _push(client: httpx.Client, kind: str, items: list[Any], size: int) -> Counter[str]:
    total: Counter[str] = Counter()
    for batch in _batches(items, size):
        response = client.post(PATHS[kind], json={"items": batch})
        if response.status_code != 200:
            sys.exit(f"{kind}: HTTP {response.status_code} {response.text[:500]}")
        for r in response.json()["items"]:
            total[r["status"]] += 1
            extra = f" field={r['field']}" if r["field"] else ""
            if r["warnings"]:
                extra += f" warnings={','.join(r['warnings'])}"
            print(f"{kind:12} {r['key']:40} {r['status']}{extra}")
    return total


def main() -> None:
    """Push every batch and print one line per item, then the totals."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count, send nothing")
    parser.add_argument("--only", choices=sorted(PATHS))
    args = parser.parse_args()
    payloads = _payloads(args.only)
    if args.dry_run:
        for kind, (items, size) in payloads.items():
            print(f"{kind}: {len(items)} items in {-(-len(items) // size)} batches")
        return
    file = _env_file()
    token = _setting("IHSP_CATALOG_PUSH_TOKEN", file)
    url = _setting("IHSP_CATALOG_PUSH_URL", file).rstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "ihsp-push-catalog/1",
    }
    with httpx.Client(base_url=url, headers=headers, timeout=300) as client:
        for kind, (items, size) in payloads.items():
            total = _push(client, kind, items, size)
            print(f"{kind}: " + ", ".join(f"{k} {v}" for k, v in sorted(total.items())))


if __name__ == "__main__":
    main()
