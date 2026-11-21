"""Org media shards: duplicate merge by domain and case-insensitive alias lookup."""

import json
from pathlib import Path

from app.modules.admission.infrastructure.org_media import (
    by_alias,
    by_domain,
    load_org_media,
)


def test_duplicates_merge_by_domain_and_aliases_union(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(
        json.dumps(
            [
                {
                    "domain": "WWW.Harvard.edu",
                    "name": "Harvard University",
                    "aliases": ["Harvard University", "Harvard"],
                    "logo_url": None,
                    "cover_url": "https://upload.wikimedia.org/a.jpg",
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            [
                {
                    "domain": "harvard.edu",
                    "name": "Harvard University",
                    "aliases": ["harvard", "Harvard Business School"],
                    "logo_url": "https://upload.wikimedia.org/logo.svg",
                    "cover_url": "https://upload.wikimedia.org/b.jpg",
                }
            ]
        ),
        encoding="utf-8",
    )

    media = load_org_media(tmp_path)

    assert len(media) == 1
    org = media[0]
    assert org.domain == "harvard.edu"
    assert org.logo_url == "https://upload.wikimedia.org/logo.svg"
    assert org.cover_url == "https://upload.wikimedia.org/a.jpg"
    assert org.aliases == (
        "Harvard University",
        "Harvard",
        "Harvard Business School",
    )


def test_alias_and_name_lookup_is_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "org.json").write_text(
        json.dumps(
            [
                {
                    "domain": "ox.ac.uk",
                    "name": "University of Oxford",
                    "aliases": ["Oxford University"],
                    "logo_url": None,
                    "cover_url": None,
                }
            ]
        ),
        encoding="utf-8",
    )

    media = load_org_media(tmp_path)

    assert by_domain(media)["ox.ac.uk"].name == "University of Oxford"
    lookup = by_alias(media)
    assert lookup["oxford university"] is media[0]
    assert lookup["university of oxford"] is media[0]
    assert "oxford" not in lookup
