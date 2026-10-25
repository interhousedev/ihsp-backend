"""Use case: outline a slide deck before it is generated (PLAN).

The model writes a numbered outline (a title and 2 to 5 bullets per slide) from the
notebook's sources; the student edits it and confirms it with "Generate". The call
is synchronous and small: a part of the Studio context, a short JSON answer.
"""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.artifact_engine import clean_prompt
from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.context_builder import ContextBuilder
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.domain.artifacts.kinds.slides import SLIDE_COUNTS
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.errors import NoSourcesSelectedError
from app.modules.notebooks.domain.language import resolve_language
from app.modules.notebooks.domain.presentation_plan import (
    PLAN_MAX_SLIDES,
    PlanSlide,
    PresentationPlan,
    clean_slides,
)
from app.modules.notebooks.domain.prompts.slides_plan import (
    PLAN_MAX_TOKENS,
    PLAN_SCHEMA_NAME,
    PlanOut,
    plan_task,
)
from app.modules.notebooks.domain.prompts.studio import studio_system_prompt
from app.modules.notebooks.domain.sources_block import render_sources_block
from app.modules.notebooks.domain.tokens import estimate_cost
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.agent_steps import StepKind, record_step
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.ids import new_id

from pydantic import ValidationError

CONTEXT_SHARE = 2  # the outline reads half of the Studio context
TITLE_CHARS = 255


class CreatePresentationPlan:
    """Asks the model for an outline and stores it as a draft plan."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        llm: NotebookLlm,
        context: ContextBuilder,
        budget: NotebookBudget,
        locale: LocaleResolver,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.llm = llm
        self.context = context
        self.budget = budget
        self.locale = locale
        self.clock = clock
        self.settings = settings

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        *,
        prompt: str | None,
        source_ids: list[UUID] | None,
        slide_count: int | None = None,
        slide_format: str = "presenter",
    ) -> PresentationPlan:
        """Return the new draft plan.

        Raises:
            NotebookNotFoundError: Not the caller's notebook.
            InvalidOptionsError: The focus text is too long.
            NoSourcesSelectedError: Sources are picked, but none is ready.
            LimitReachedError: The weighted-token budget is used up.
        """
        focus = clean_prompt(prompt)
        cap = self.settings.notebooks.studio_context_tokens // CONTEXT_SHARE
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id)
            sources = await _pick_sources(uow, notebook, source_ids)
            pack = await self.context.for_studio(
                uow, notebook.id, sources, prompt=focus, cap_tokens=cap
            )
        count = min(slide_count or SLIDE_COUNTS["default"], PLAN_MAX_SLIDES)
        messages = [
            self.llm.context_message(render_sources_block(pack), AiTask.STUDIO_SLIDES),
            {
                "role": "user",
                "content": plan_task(count=count, limit=PLAN_MAX_SLIDES, prompt=focus),
            },
        ]
        language = resolve_language(None, await self.locale.locale_of(actor.user_id))
        system = studio_system_prompt(language)
        max_tokens = self.llm.max_tokens(AiTask.STUDIO_SLIDES, PLAN_MAX_TOKENS)
        pool = self.budget.pool(notebook.is_course_workspace)
        chars = len(system) + sum(len(str(m["content"])) for m in messages)
        await pool.require(actor.user_id, estimate_cost(chars, max_tokens))
        done = await self.llm.json(
            task=AiTask.STUDIO_SLIDES,
            system=system,
            messages=messages,
            schema_name=PLAN_SCHEMA_NAME,
            schema=to_strict_schema(PlanOut),
            max_tokens=max_tokens,
        )
        await pool.add(actor.user_id, done.usage.weighted)
        plan = self._plan(actor, notebook, done.data, focus, sources)
        plan.format = slide_format
        async with self.uow_factory() as uow:
            await uow.plans.add(plan)
            await uow.commit()
        record_step(
            StepKind.CREATE, "Created plan", target=plan.title, ref=str(plan.id)
        )
        return plan

    def _plan(
        self,
        actor: Actor,
        notebook: Notebook,
        data: dict[str, Any],
        focus: str | None,
        sources: list[Source],
    ) -> PresentationPlan:
        now = self.clock.now()
        title = " ".join(str(data.get("title") or "").split())[:TITLE_CHARS]
        return PresentationPlan(
            id=new_id(),
            notebook_id=notebook.id,
            owner_id=actor.user_id,
            title=title or notebook.title[:TITLE_CHARS],
            slides=_slides_of(data)[:PLAN_MAX_SLIDES],
            created_at=now,
            updated_at=now,
            prompt=focus,
            source_ids=[source.id for source in sources],
        )


def _slides_of(data: dict[str, Any]) -> list[PlanSlide]:
    """The model's slides that are valid, cleaned (a broken one is skipped)."""
    raw = data.get("slides")
    slides: list[PlanSlide] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            slides.append(PlanSlide.model_validate(item))
        except ValidationError:
            continue
    return clean_slides(slides)


async def _pick_sources(
    uow: NotebooksUnitOfWork, notebook: Notebook, wanted_ids: list[UUID] | None
) -> list[Source]:
    """The ready sources: the given ids, else the selection (as a Studio request)."""
    wanted = set(wanted_ids or [])
    sources = await uow.sources.list_for_notebook(notebook.id)
    chosen = [
        source
        for source in sources
        if source.usable and (source.id in wanted if wanted else source.selected)
    ]
    if not chosen and (wanted or any(source.selected for source in sources)):
        raise NoSourcesSelectedError()
    return chosen
