"""Write openapi/openapi.json from the `all` application (no service is contacted).

IHSP_ENV_FILE=materials/dev.env uv run python scripts/export_openapi.py [path]
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app.bootstrap.common import build_container
from app.bootstrap.http_app import build_http_app
from app.settings import load_settings

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "openapi" / "openapi.json"


class NullKicker:
    """TaskKicker that drops every task (nothing is started while exporting)."""

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        """Ignore the task."""


async def build_schema() -> dict[str, Any]:
    """The OpenAPI document of the `all` process, built with development settings."""
    container = await build_container(
        load_settings(), process="all", kicker=NullKicker()
    )
    try:
        schema: dict[str, Any] = build_http_app(container, process="all").openapi()
    finally:
        await container.close()
    return schema


def main() -> int:
    """Export the schema with sorted keys so diffs stay small."""
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    schema = asyncio.run(build_schema())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    paths = schema["paths"]
    sys.stdout.write(f"{target}: {len(paths)} paths\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
