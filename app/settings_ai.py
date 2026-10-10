"""AI model settings: one default and an override per task (`IHSP_AI__...`).

    IHSP_AI__DEFAULT__MODEL=anthropic/claude-haiku-4.5
    IHSP_AI__DEFAULT__TEMPERATURE=0.2
    IHSP_AI__TASKS__STUDIO_QUIZ__MODEL=anthropic/claude-sonnet-5.5
    IHSP_AI__TASKS__STUDIO_QUIZ__FALLBACKS=anthropic/claude-haiku-4.5

A task takes its own value, else the value the code gives that task (the smart tier
ships with a larger model), else the default. The task names are `AiTask`.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.shared.ai_tasks import (
    ALL_MODALITIES,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    LIGHT_NOTEBOOK_TASKS,
    NOTEBOOK_TASKS,
    TASK_SPECS,
    AiTask,
    DataCollection,
    Modality,
    ModelProfile,
)
from app.shared.contracts.ai import ReasoningEffort

import structlog
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from app.settings import Settings

log = structlog.get_logger(__name__)

DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


def _comma_list(value: object) -> object:
    """Turn `a, b` from the environment into a tuple (a JSON list works too)."""
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return value


class AiDefaults(BaseModel):
    """What every task uses unless the task sets its own value."""

    model: str = Field(default=DEFAULT_MODEL, min_length=1)
    """OpenRouter model id used by every task without its own model."""

    temperature: float = Field(default=0.2, ge=0, le=2)
    """Sampling temperature."""

    max_output_tokens: int | None = Field(default=None, ge=1)
    """Answer size limit; empty keeps each call site's own size (chat length, kind)."""

    reasoning_effort: ReasoningEffort | None = None
    """Reasoning effort for models that support it (low, medium or high); empty: off."""

    fallbacks: tuple[str, ...] = ()
    """Comma list of models OpenRouter tries when the model or its providers fail."""

    budget_weight: int = Field(default=1, ge=1)
    """How many budget tokens one model token counts for (the smart tier uses more)."""

    data_collection: DataCollection | None = None
    """OpenRouter `provider.data_collection` (deny or allow); empty sends nothing."""

    provider_order: tuple[str, ...] = ()
    """Comma list of OpenRouter providers to try first (`provider.order`)."""

    modalities: tuple[Modality, ...] = ALL_MODALITIES
    """Comma list of the inputs the model reads: text, image, audio, video, pdf."""

    @field_validator("fallbacks", "provider_order", "modalities", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        return _comma_list(value)


class AiTaskSettings(BaseModel):
    """Overrides of one task (`IHSP_AI__TASKS__<TASK>__<FIELD>`); empty inherits."""

    model: str | None = Field(default=None, min_length=1)
    """Model id for this task."""

    temperature: float | None = Field(default=None, ge=0, le=2)
    """Sampling temperature for this task."""

    max_output_tokens: int | None = Field(default=None, ge=1)
    """Answer size limit; replaces the call site's own size (chat length too)."""

    reasoning_effort: ReasoningEffort | None = None
    """Reasoning effort for this task (low, medium or high)."""

    fallbacks: tuple[str, ...] | None = None
    """Comma list of fallback models for this task."""

    budget_weight: int | None = Field(default=None, ge=1)
    """Budget multiplier for this task's tokens."""

    data_collection: DataCollection | None = None
    """OpenRouter `provider.data_collection` for this task (deny or allow)."""

    provider_order: tuple[str, ...] | None = None
    """Comma list of OpenRouter providers to try first for this task."""

    modalities: tuple[Modality, ...] | None = None
    """Comma list of the inputs this task's model reads (text, image, audio, video, pdf)."""

    dimensions: int | None = Field(default=None, ge=1)
    """Embedding task only: vector size. It must equal the `vectors.embeddings`
    column (1024); a model that cannot produce that size cannot be used."""

    batch_size: int | None = Field(default=None, ge=1, le=256)
    """Embedding task only: texts sent in one request."""

    query_prefix: str | None = None
    """Embedding task only: text put before a question (some models need a task line,
    e.g. `query: ` for multilingual-e5). `none` removes the built-in line."""

    document_prefix: str | None = None
    """Embedding task only: text put before a passage (e.g. `passage: ` for e5)."""

    @field_validator("query_prefix", "document_prefix", mode="after")
    @classmethod
    def _none_means_empty(cls, value: str | None) -> str | None:
        return "" if value is not None and value.strip().lower() == "none" else value

    @field_validator("fallbacks", "provider_order", "modalities", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        return _comma_list(value)


def _first[T](*values: T | None) -> T:
    """The first value that is not None (the last one always is)."""
    for value in values:
        if value is not None:
            return value
    raise ValueError("no value")  # pragma: no cover


class AiSettings(BaseModel):
    """Language models: a default and a per-task override (`AI__DEFAULT__*`)."""

    default: AiDefaults = Field(default_factory=AiDefaults)
    """Defaults of every task."""

    tasks: dict[AiTask, AiTaskSettings] = Field(default_factory=dict)
    """Per-task overrides, keyed by task name (see the task list above)."""

    def profile(self, task: AiTask) -> ModelProfile:
        """The model and parameters of a task (override, built-in, default)."""
        spec = TASK_SPECS[task]
        own = self.tasks.get(task) or AiTaskSettings()
        base = self.default
        return ModelProfile(
            task=task,
            model=_first(own.model, spec.model, base.model),
            temperature=_first(own.temperature, base.temperature),
            max_output_tokens=own.max_output_tokens or base.max_output_tokens,
            reasoning_effort=own.reasoning_effort or base.reasoning_effort,
            fallbacks=_first(own.fallbacks, base.fallbacks),
            data_collection=own.data_collection
            or spec.data_collection
            or base.data_collection,
            provider_order=_first(own.provider_order, base.provider_order),
            budget_weight=_first(
                own.budget_weight, spec.budget_weight, base.budget_weight
            ),
            modalities=_first(own.modalities, base.modalities),
            dimensions=_first(own.dimensions, spec.dimensions, EMBEDDING_DIMENSIONS),
            batch_size=_first(own.batch_size, spec.batch_size, EMBEDDING_BATCH_SIZE),
            query_prefix=_first(own.query_prefix, spec.query_prefix, ""),
            document_prefix=_first(own.document_prefix, spec.document_prefix, ""),
        )


@dataclass(frozen=True, slots=True)
class _Move:
    """One deprecated variable and where its value goes now."""

    old: str
    new: str  # the variable that replaces it, for the log line
    value: str | int | None
    field: str
    tasks: frozenset[AiTask]


def _moves(settings: "Settings") -> list[_Move]:
    router, limits = settings.openrouter, settings.limits
    notebooks = NOTEBOOK_TASKS
    if router.model_notebook_light:
        notebooks = notebooks - LIGHT_NOTEBOOK_TASKS
    return [
        _Move(
            "OPENROUTER__MODEL_STUDENT",
            "AI__TASKS__STUDENT_CHAT__MODEL",
            router.model_student,
            "model",
            frozenset({AiTask.STUDENT_CHAT}),
        ),
        _Move(
            "OPENROUTER__MODEL_STUDENT_SMART",
            "AI__TASKS__STUDENT_CHAT_SMART__MODEL",
            router.model_student_smart,
            "model",
            frozenset({AiTask.STUDENT_CHAT_SMART}),
        ),
        _Move(
            "OPENROUTER__MODEL_ADMIN",
            "AI__TASKS__ADMIN_CHAT__MODEL",
            router.model_admin,
            "model",
            frozenset({AiTask.ADMIN_CHAT}),
        ),
        _Move(
            "OPENROUTER__MODEL_NOTEBOOK",
            "AI__TASKS__NOTEBOOK_CHAT__MODEL and the STUDIO_* tasks",
            router.model_notebook,
            "model",
            notebooks,
        ),
        _Move(
            "OPENROUTER__MODEL_NOTEBOOK_LIGHT",
            "AI__TASKS__SOURCE_GUIDE__MODEL and ..NOTEBOOK_SUMMARY__MODEL",
            router.model_notebook_light,
            "model",
            LIGHT_NOTEBOOK_TASKS,
        ),
        _Move(
            "OPENROUTER__NOTEBOOK_DATA_COLLECTION",
            "AI__TASKS__<NOTEBOOK TASK>__DATA_COLLECTION",
            router.notebook_data_collection,
            "data_collection",
            NOTEBOOK_TASKS,
        ),
        _Move(
            "LIMITS__AI_SMART_WEIGHT",
            "AI__TASKS__STUDENT_CHAT_SMART__BUDGET_WEIGHT",
            limits.ai_smart_weight,
            "budget_weight",
            frozenset({AiTask.STUDENT_CHAT_SMART}),
        ),
    ]


def fold_deprecated(settings: "Settings") -> None:
    """Map the old `OPENROUTER__MODEL_*` style variables onto the task overrides.

    A deprecated variable fills only what the task's own `AI__TASKS__...` leaves
    empty, and every one that is set is logged as a warning.
    """
    tasks = dict(settings.ai.tasks)
    for move in _moves(settings):
        if move.value is None:
            continue
        log.warning(
            "settings.deprecated_variable",
            variable=f"IHSP_{move.old}",
            use=f"IHSP_{move.new}",
        )
        for task in move.tasks:
            current = tasks.get(task) or AiTaskSettings()
            if getattr(current, move.field) is None:
                tasks[task] = current.model_copy(update={move.field: move.value})
    settings.ai = settings.ai.model_copy(update={"tasks": tasks})
