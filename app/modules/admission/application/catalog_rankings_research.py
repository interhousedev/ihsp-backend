"""Propose rankings and experience scores of an institution from web pages.

Only values with a source URL that the search returned are kept, so the model
cannot invent a source. Facts are proposals for a curator, never published here.
"""

import json
from typing import Any

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.shared.ai_tasks import AiTask

from pydantic import BaseModel, Field

SYSTEM = (
    "You extract university facts from the web pages given. Use ONLY the pages. "
    "Return rankings (system qs|the|arwu|usnews; subject `overall` for the "
    "institution's overall world ranking, or a slug such as "
    "computer_science, business, engineering, medicine, rank as a whole number or "
    "a band like 201-250, year, the page URL) and, only when a page supports it, "
    "1-5 ratings of social life, research and work-experience opportunities with a "
    "short note in en, ru and uz. Leave anything unsupported out. Never guess. "
    'Answer with ONE JSON object {"rankings": [...], "experience": [...]}; '
    "use empty lists when the pages support nothing."
)


class RankingItem(BaseModel):
    """One ranking read from a page."""

    system: str
    subject: str = Field(max_length=40)
    rank: str = Field(description="Whole number or band, e.g. 12 or 201-250.")
    year: int
    source_url: str


class ExperienceItem(BaseModel):
    """Ratings 1..5; 0 means the pages say nothing."""

    social: int = Field(ge=0, le=5)
    research: int = Field(ge=0, le=5)
    work: int = Field(ge=0, le=5)
    note_en: str = Field(max_length=160)
    note_ru: str = Field(max_length=160)
    note_uz: str = Field(max_length=160)
    source_url: str


class ResearchOut(BaseModel):
    """The structured answer."""

    rankings: list[RankingItem] = Field(max_length=10)
    experience: list[ExperienceItem] = Field(max_length=1)


def facts_from(
    out: ResearchOut, allowed: set[str], year: int
) -> dict[str, dict[str, Any]]:
    """Fact payloads (`clean_facts` input) of the answer, from `allowed` URLs."""
    facts: dict[str, dict[str, Any]] = {}
    rows = []
    for r in out.rankings:
        if r.source_url not in allowed:
            continue
        rank: Any = int(r.rank) if r.rank.isdigit() else r.rank
        rows.append({**r.model_dump(), "rank": rank})
    if rows:
        facts["rankings"] = {
            "value": rows,
            "source_url": rows[0]["source_url"],
            "year": year,
        }
    for e in out.experience:
        if e.source_url not in allowed:
            continue
        value: dict[str, Any] = {
            k: getattr(e, k) for k in ("social", "research", "work") if getattr(e, k)
        }
        if not value:
            continue
        notes = {
            k: {"en": e.note_en, "ru": e.note_ru, "uz": e.note_uz}
            for k in value
            if e.note_en and e.note_ru and e.note_uz
        }
        if notes:
            value["notes"] = notes
        facts["experience_scores"] = {
            "value": value,
            "source_url": e.source_url,
            "year": year,
        }
    return facts


async def research(
    llm: NotebookLlm, name: str, country: str, pages: list[dict[str, str]], year: int
) -> dict[str, dict[str, Any]]:
    """Ask the model about one institution's pages; return validated-shape facts."""
    result = await llm.json(
        task=AiTask.ADMIT_CATALOG_RESEARCH,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    {"institution": name, "country": country, "pages": pages}
                ),
            }
        ],
        schema_name="admission_catalog_research",
        schema=to_strict_schema(ResearchOut),
        max_tokens=3000,
    )
    if "rankings" not in result.data:  # cut-off answer: only a fragment parsed
        return {}
    return facts_from(
        ResearchOut.model_validate(result.data), {p["url"] for p in pages}, year
    )
