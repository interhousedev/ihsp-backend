"""Write licenses/python.json: the production Python dependencies and licenses.

uv run python scripts/export_licenses.py [path]

The names come from the lock file (`uv export --no-dev`); no service is contacted.
The license and the project link come from the metadata of the installed
distributions, so run `uv sync --frozen` first. The web repository reads this file
when it regenerates its own license list (`bun run generate-licenses`).
"""

import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "licenses" / "python.json"
UNKNOWN = "UNKNOWN"
REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
URL_LABELS = ("homepage", "home", "source", "repository", "source code")


def canonical(name: str) -> str:
    """The PEP 503 name: lower case, runs of `-_.` as one dash."""
    return re.sub(r"[-_.]+", "-", name).lower()


def production_requirements() -> dict[str, bool]:
    """Runtime dependency names from the lock file, with a flag for markers."""
    result = subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--no-header",
            "--no-annotate",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    requirements: dict[str, bool] = {}
    for line in result.stdout.splitlines():
        match = REQUIREMENT.match(line.strip())
        if match:
            requirements[canonical(match.group(1))] = ";" in line
    return requirements


def license_of(meta: Any) -> str:
    """The PEP 639 expression, else the License field, else the classifiers."""
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    field = (meta.get("License") or "").strip()
    if field and "\n" not in field and len(field) <= 80:
        return field
    classifiers = [
        item.split(" :: ")[-1].strip()
        for item in meta.get_all("Classifier") or []
        if item.startswith("License :: ")
    ]
    return "; ".join(sorted(set(classifiers))) or UNKNOWN


def project_url(meta: Any, name: str) -> str:
    """The homepage or source link when the metadata has one, else the PyPI page."""
    links: dict[str, str] = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        links.setdefault(label.strip().lower(), url.strip())
    for label in URL_LABELS:
        url = links.get(label, "")
        if url.startswith("https://"):
            return url
    home = (meta.get("Home-page") or "").strip()
    if home.startswith("https://"):
        return home
    return f"https://pypi.org/project/{name}/"


def collect() -> list[dict[str, str]]:
    """One row per production distribution, sorted by name and version.

    A dependency with an environment marker (for example emscripten only) that is not
    installed on this machine is skipped; any other missing one stops the export.
    """
    rows: list[dict[str, str]] = []
    for name, has_marker in production_requirements().items():
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError as error:
            if has_marker:
                continue
            raise SystemExit(
                f"{name} is not installed: run `uv sync --frozen` first"
            ) from error
        meta = dist.metadata
        rows.append(
            {
                "name": meta["Name"],
                "version": dist.version,
                "license": license_of(meta),
                "url": project_url(meta, meta["Name"]),
                "ecosystem": "PyPI",
            }
        )
    return sorted(rows, key=lambda row: (row["name"].lower(), row["version"]))


def main() -> int:
    """Write the JSON with sorted keys, so diffs stay small."""
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    rows = collect()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"packages": rows}, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    unknown = sum(1 for row in rows if row["license"] == UNKNOWN)
    sys.stdout.write(f"{target}: {len(rows)} packages, {unknown} without license\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
