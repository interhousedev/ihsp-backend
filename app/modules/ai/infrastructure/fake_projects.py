"""Deterministic fake document for the admission project ideas."""

from typing import Any

PROJECTS_SCHEMA = "project_ideas"

_THEMES = (
    ("school-repair-map", "Map of school repairs", ["website_tech", "org_outreach"]),
    ("peer-tutoring", "Peer tutoring circle", ["org_outreach", "business_growth"]),
    ("local-news-bot", "Neighbourhood news bot", ["website_tech", "product_dev"]),
    ("recycling-drive", "Recycling drive", ["org_outreach", "fundraising"]),
    ("study-notes-hub", "Open study notes hub", ["website_tech", "product_dev"]),
    ("history-podcast", "Local history podcast", ["pitching", "org_outreach"]),
    ("coding-club", "Coding club for juniors", ["product_dev", "business_growth"]),
    ("craft-shop", "Online shop for local crafts", ["business_growth", "pitching"]),
    ("water-sensor", "Classroom air-quality sensor", ["product_dev", "fundraising"]),
    ("language-buddies", "Language buddies", ["org_outreach", "website_tech"]),
    ("charity-run", "Charity run", ["fundraising", "org_outreach"]),
    ("science-fair", "Mini science fair", ["pitching", "fundraising"]),
)


_ANALOGS = [
    {"name": "A local student initiative", "where": "uzbekistan", "url": ""},
    {"name": "An open-source community project", "where": "abroad", "url": ""},
]


def build_project_ideas_document(schema_name: str) -> dict[str, Any] | None:
    """Return a schema-valid list of 12 plausible projects, else None."""
    if schema_name != PROJECTS_SCHEMA:
        return None
    return {
        "projects": [
            {
                "key": key,
                "title": title,
                "summary": "You start small with one group of people, test the idea "
                "for a month and write down what changed.",
                "analogs": _ANALOGS,
                "challenges": ["Finding time every week", "Getting the first users"],
                "application_effect": "Shows initiative and a measurable result you "
                "can describe in an essay and an activity entry.",
                "first_steps": [
                    "Write the goal in one sentence",
                    "Talk to three people who would use it",
                    "Make a one-page plan",
                ],
                "help_tags": tags,
            }
            for key, title, tags in _THEMES
        ]
    }
