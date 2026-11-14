"""B3: server instructions: brand placeholders, school terms, all three languages."""

import json
import re
from pathlib import Path

from app.interfaces.mcp.constants import ServerName
from app.shared.brand import current_brand
from app.shared.paths import LOCALES_DIR
from tests.mcp.conftest import World

import pytest
from mcp.client.session import ClientSession

LANGUAGES = ("en", "ru", "uz")
KEYS = (
    "mcp-instructions-student",
    "mcp-instructions-lms",
    "mcp-instructions-admin",
    "mcp-instructions-teacher",
    "mcp-instructions-app",
)


def _texts(language: str) -> dict[str, str]:
    path = Path(LOCALES_DIR) / language / "mcp.json"
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return {key: data[key] for key in KEYS}


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("key", KEYS)
def test_text_holds_placeholders_and_no_literal_brand(language: str, key: str) -> None:
    """D10: a rebrand changes settings only."""
    text = _texts(language)[key]

    assert "{brand}" in text
    assert "{org_name}" in text
    for literal in ("IHT", "IHSP", "International House", "Interhouse", "ihsu.uz"):
        assert literal not in text


@pytest.mark.parametrize("language", LANGUAGES)
def test_student_text_names_both_controls_and_no_forbidden_term(language: str) -> None:
    """B3: ПК and ИК in every language, "Рубежный" nowhere."""
    text = _texts(language)["mcp-instructions-student"]

    assert "ПК" in text and "ИК" in text
    assert "убежн" not in text


@pytest.mark.parametrize("key", KEYS)
def test_uzbek_uses_the_modifier_apostrophe(key: str) -> None:
    """Copy rule: ʼ only."""
    text = _texts("uz")[key]

    assert not re.search("['’]", text)


@pytest.mark.parametrize("language", LANGUAGES)
def test_student_text_tells_the_client_that_results_are_data(language: str) -> None:
    """B3: the `pending` protocol and `links` are named literally in every language."""
    text = _texts(language)["mcp-instructions-student"]

    assert "status" in text and "pending" in text
    assert "links" in text
    assert "insufficient_scope" in text


@pytest.mark.parametrize("server", ["student", "lms", "admin", "teacher", "app"])
async def test_client_receives_the_brand_filled_in(
    world: World, server: ServerName
) -> None:
    """B3: the placeholders never reach a client."""
    token, _ = world.connector_token(server)

    async with world.serve() as running:
        async with running.session(server, token) as session:
            instructions = await _instructions(session)

    assert current_brand().name in instructions
    assert current_brand().org_name in instructions
    assert "{" not in instructions


async def _instructions(session: ClientSession) -> str:
    """The instructions sent on initialize (a second initialize is harmless)."""
    result = await session.initialize()
    return result.instructions or ""
