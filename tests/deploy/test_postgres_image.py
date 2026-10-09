"""NB-14: every compose file runs PostgreSQL with pgvector (vectors_0001 needs it)."""

import re
from pathlib import Path

from tests.deploy.helpers import LOCAL_COMPOSE, MATERIALS_DIR, PROD_COMPOSE

import pytest

DEV_COMPOSE = MATERIALS_DIR / "docker-compose.dev.yaml"
IMAGE = "pgvector/pgvector:pg16"


@pytest.mark.parametrize("compose_file", [DEV_COMPOSE, LOCAL_COMPOSE, PROD_COMPOSE])
def test_postgres_is_the_pgvector_image(compose_file: Path) -> None:
    """Same Postgres 16 major version as before, plus the `vector` extension."""
    text = compose_file.read_text(encoding="utf-8")
    block = re.search(r"^  postgres:\n(?:    .*\n|\n)+", text, re.MULTILINE)

    assert block is not None
    assert f"image: {IMAGE}" in block.group(0)
    assert "image: postgres:" not in text
