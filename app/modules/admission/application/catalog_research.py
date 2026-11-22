"""Optional AI summary of one catalog institution, from published facts only."""

import json
from typing import Any
from uuid import UUID

from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.focuses import served_focuses
from app.modules.admission.ports.ai import PromptSource
from app.modules.admission.ports.unit_of_work import UowFactory
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand

from pydantic import BaseModel, Field


class ResearchPoint(BaseModel):
    """One statement and the source it rests on."""

    text: str = Field(max_length=300)
    source_url: str


class ResearchSummary(BaseModel):
    """The structured answer."""

    summary: str = Field(max_length=800)
    points: list[ResearchPoint] = Field(max_length=8)
    missing: list[str] = Field(max_length=8)


class CatalogResearch:
    """Summarises the facts of an institution; the result is not stored."""

    def __init__(
        self, uow_factory: UowFactory, llm: NotebookLlm, prompts: PromptSource
    ) -> None:
        """Keep the unit-of-work factory, the model wrapper and the prompts."""
        self._uow = uow_factory
        self._llm = llm
        self._prompts = prompts

    async def summarise(self, institution_id: UUID, language: str) -> dict[str, Any]:
        """Return `{summary, points, missing}`; only published facts are sent."""
        async with self._uow() as uow:
            inst = await uow.catalog.institution(institution_id)
        if inst is None:
            raise AdmissionNotFoundError()
        facts = {
            k: {"value": f.value, "source_url": f.source_url, "year": f.year}
            for k, f in inst.facts.items()
            if f.value is not None and k != "focuses"
        }
        focuses = served_focuses(
            inst.facts["focuses"].value if "focuses" in inst.facts else None,
            inst.website_domain,
        )
        if focuses:
            facts["focuses"] = {
                "value": focuses,
                "source_url": focuses[0]["source_url"],
                "year": None,
            }
        payload = {"name": inst.name, "country": inst.country, "facts": facts}
        result = await self._llm.json(
            task=AiTask.ADMIT_UNIVERSITY_RESEARCH,
            system=with_brand(
                await self._prompts.text(
                    AiTask.ADMIT_UNIVERSITY_RESEARCH, "system", language
                )
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Language: {language}\n" f"{json.dumps(payload, default=str)}"
                    ),
                }
            ],
            schema_name="admission_university_summary",
            schema=to_strict_schema(ResearchSummary),
            max_tokens=900,
        )
        known = {f.source_url for f in inst.facts.values()}
        out = ResearchSummary.model_validate(result.data)
        out.points = [p for p in out.points if p.source_url in known]
        return out.model_dump()
