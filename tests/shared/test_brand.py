"""The brand is one value: placeholders in locales and prompts, filled once."""

import json
from pathlib import Path

from app.shared.brand import current_brand, with_brand

LOCALES = Path(__file__).parents[2] / "locales"


def test_with_brand_fills_its_placeholders_and_keeps_the_others() -> None:
    brand = current_brand()
    text = with_brand("{brand} {brand_id} {org_name} {language}")
    assert text == f"{brand.name} {brand.id_name} {brand.org_name} {{language}}"


def test_locale_files_hold_no_literal_brand() -> None:
    for path in LOCALES.glob("*/*.json"):
        text = json.dumps(json.loads(path.read_text("utf-8")), ensure_ascii=False)
        for literal in ("IHT", "Interhouse", "International House", "library.iht"):
            assert literal not in text, f"{path}: {literal}"
