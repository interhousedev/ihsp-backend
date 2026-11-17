from app.modules.admission.domain.supp_prompts import (
    MAX_PROMPT_LEN,
    MAX_PROMPTS,
    MAX_URL_LEN,
    MAX_WORD_LIMIT,
    CyclePrompts,
    PromptStatus,
    SuppPrompt,
)
class SuppPromptOut(BaseModel):
    """A prompt of a cycle; `status` compares it with the cycle before.

    `previous_text` is the old wording of a `changed` prompt.
    """

    position: int
    prompt: str
    word_limit: int | None
    required: bool
    source_url: str | None
    status: PromptStatus
    previous_text: str | None


class SuppCycleOut(BaseModel):
    """The prompts of one admission cycle, e.g. `2025-26`."""

    cycle: str
    prompts: list[SuppPromptOut]


class SuppPromptIn(BaseModel):
    """One prompt to store; the list order gives the position."""

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LEN)
    word_limit: int | None = Field(default=None, ge=1, le=MAX_WORD_LIMIT)
    required: bool = True
    source_url: str | None = Field(default=None, max_length=MAX_URL_LEN)


class SuppPromptsPutIn(BaseModel):
    """The full prompt list of a cycle."""

    prompts: list[SuppPromptIn] = Field(max_length=MAX_PROMPTS)


def _cycles_out(cycles: list[CyclePrompts]) -> list[SuppCycleOut]:
    return [
        SuppCycleOut(
            cycle=c.cycle,
            prompts=[
                SuppPromptOut(
                    position=p.prompt.position,
                    prompt=p.prompt.prompt,
                    word_limit=p.prompt.word_limit,
                    required=p.prompt.required,
                    source_url=p.prompt.source_url,
                    status=p.status,
                    previous_text=p.previous_text,
                )
                for p in c.prompts
            ],
        )
        for c in cycles
    ]


async def get_supp_prompts(
    institution_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> list[SuppCycleOut]:
    """Supplemental prompts per cycle, newest first, with changes since last year."""
    return _cycles_out(await container.admission.supp_prompts.cycles(institution_id))


async def put_staff_supp_prompts(
    institution_id: UUID,
    cycle: str,
    body: SuppPromptsPutIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> list[SuppCycleOut]:
    """Replace the prompts of one cycle (curator roles); returns every cycle."""
    prompts = [
        SuppPrompt(i, p.prompt, p.word_limit, p.required, p.source_url)
        for i, p in enumerate(body.prompts)
    ]
    cycles = await container.admission.supp_prompts.replace(
        ctx, institution_id, cycle, prompts
    )
    return _cycles_out(cycles)


_R(
    "/catalog/institutions/{institution_id}/supp-prompts",
    get_supp_prompts,
    methods=["GET"],
    response_model=list[SuppCycleOut],
    operation_id="admission_catalog_supp_prompts",
)
_R(
    "/staff/catalog/institutions/{institution_id}/supp-prompts/{cycle}",
    put_staff_supp_prompts,
    methods=["PUT"],
    response_model=list[SuppCycleOut],
    operation_id="admission_staff_catalog_supp_prompts_put",
)