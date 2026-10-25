"""Catalog of the language model tasks: one name for each place that calls a model.

Modules ask for a task (`settings.ai_profile(AiTask.STUDIO_QUIZ)`) and never for a
model name. The settings (`AI__DEFAULT__*` and `AI__TASKS__<TASK>__*`) decide which
model, temperature, limits and routing the task gets; this file only lists the tasks
and what is special about each one.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

from app.shared.contracts.ai import LlmTuning, ReasoningEffort

DataCollection = Literal["deny", "allow"]
Modality = Literal["text", "image", "audio", "video", "pdf"]
ALL_MODALITIES: tuple[Modality, ...] = ("text", "image", "audio", "video", "pdf")

SMART_MODEL: Final = "google/gemini-3.8-flash"
# Repairs broken OpenUI blocks: the cheapest Qwen coder on OpenRouter (2026-10; the
# 2.5 7B coder is not listed there), about USD 0.07 / 0.28 per 1M tokens.
OPENUI_REPAIR_MODEL: Final = "qwen/qwen3-coder-30b-a3b-instruct"
# Notebook guides, summaries, labels and Studio outputs: the Claude Haiku 5.5 JSON
# outputs scored best in the 2026-10 studio bench (ru, thin and long sources) at a
# tenth of the price of Haiku 4.5; reasoning is switched off for them (below).
NOTEBOOK_MODEL: Final = "anthropic/claude-haiku-5.5"
# The smart tier: Gemini 3.8 Flash at `low` effort (benchmarked: no reasoning tokens,
# good answers) costs about 7.5x Claude Haiku 5.5, so one smart token counts 8x.
SMART_REASONING: Final = "low"
SMART_BUDGET_WEIGHT: Final = 8
# Vectors for meaning-based retrieval: multilingual
# (Uzbek Latin and Cyrillic, Russian, English), 32k context, USD 0.02 per 1M tokens.
TRANSLATE_MODEL: Final = "google/gemini-3.5-flash-lite"  # cheap; a few words per call
# Retrieval planning, query splitting and faithfulness checks: short JSON verdicts.
CHEAP_MODEL: Final = TRANSLATE_MODEL
# Summaries of older chat turns: the cheapest configured chat model.
COMPACT_MODEL: Final = TRANSLATE_MODEL
# Reads images and audio (Gemini Flash-Lite class): describes gathered media cheaply.
MEDIA_MODEL: Final = "google/gemini-3.5-flash-lite"
EMBEDDING_MODEL: Final = "qwen/qwen3-embedding-4b"
EMBEDDING_DIMENSIONS: Final = 1024  # must equal the `vectors.embeddings` column size
EMBEDDING_BATCH_SIZE: Final = 32
# Qwen3-Embedding reads a task line before a question (not before a passage).
EMBEDDING_QUERY_PREFIX: Final = (
    "Instruct: Given a student question, retrieve the study material passage "
    "that answers it\nQuery: "
)


class AiTask(StrEnum):
    """Everything an LLM is asked to do. The value is the key in the environment."""

    STUDENT_CHAT = "student_chat"
    STUDENT_CHAT_SMART = "student_chat_smart"
    ADMIN_CHAT = "admin_chat"
    GUEST_CHAT = "guest_chat"
    CHAT_SUMMARY = "chat_summary"
    CONTEXT_COMPACT = "context_compact"
    NOTEBOOK_CHAT = "notebook_chat"
    SOURCE_GUIDE = "source_guide"
    SOURCE_VISION_EXTRACT = "source_vision_extract"
    NOTEBOOK_SUMMARY = "notebook_summary"
    SOURCE_LABELS = "source_labels"
    STUDIO_REPORT = "studio_report"
    STUDIO_MIND_MAP = "studio_mind_map"
    STUDIO_FLASHCARDS = "studio_flashcards"
    STUDIO_QUIZ = "studio_quiz"
    STUDIO_DATA_TABLE = "studio_data_table"
    STUDIO_SLIDES = "studio_slides"
    STUDIO_SLIDES_REVISE = "studio_slides_revise"
    STUDIO_INFOGRAPHIC = "studio_infographic"
    STUDIO_EXERCISE = "studio_exercise"
    EXERCISE_FEEDBACK = "exercise_feedback"
    LMS_AUTHORING = "lms_authoring"
    WEB_SEARCH = "web_search"
    DISCOVER = "discover"
    SUBJECT_TRANSLATE = "subject_translate"
    EMBEDDING = "embedding"
    RETRIEVAL_PLAN = "retrieval_plan"
    QUERY_DECOMPOSE = "query_decompose"
    STUDIO_FAITHFULNESS = "studio_faithfulness"
    STUDIO_SOURCE_PROFILE = "studio_source_profile"
    STUDIO_ASSESSMENT_PLAN = "studio_assessment_plan"
    STUDIO_ITEM_VERIFY = "studio_item_verify"
    WEB_MATERIAL_TRIAGE = "web_material_triage"
    MEDIA_DESCRIBE = "media_describe"
    OPENUI_REPAIR = "openui_repair"


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """What the code knows about a task before any configuration.

    A value set here beats `AI__DEFAULT__*` and loses to `AI__TASKS__<TASK>__*`.
    """

    group: Literal["assistant", "notebooks", "lms", "search", "retrieval", "academic"]
    summary: str
    model: str | None = None  # None: the default model
    budget_weight: int | None = None  # None: the default weight
    data_collection: DataCollection | None = None  # None: the default
    reasoning_effort: ReasoningEffort | None = None  # None: the default
    # Embedding tasks only (see `AiTask.EMBEDDING`):
    dimensions: int | None = None
    batch_size: int | None = None
    query_prefix: str | None = None
    document_prefix: str | None = None


_PRIVATE: Final = "deny"  # students' own documents never go to providers that train
# Notebook outputs are JSON with a tight answer budget: models that reason by
# default (Claude 5.5, GPT-5.x) would spend it on thinking, so reasoning is off
# unless a task sets `AI__TASKS__<TASK>__REASONING_EFFORT`.
_NO_REASONING: Final = "none"

TASK_SPECS: Final[dict[AiTask, TaskSpec]] = {
    AiTask.STUDENT_CHAT: TaskSpec(
        "assistant", "Student assistant, fast tier (the default of a new chat)."
    ),
    AiTask.STUDENT_CHAT_SMART: TaskSpec(
        "assistant",
        "Student assistant, smart tier. Ships with a larger model and counts "
        f"{SMART_BUDGET_WEIGHT}x against the token budget; a few requests a week.",
        model=SMART_MODEL,
        budget_weight=SMART_BUDGET_WEIGHT,
        reasoning_effort=SMART_REASONING,
    ),
    AiTask.ADMIN_CHAT: TaskSpec("assistant", "Administration assistant."),
    AiTask.GUEST_CHAT: TaskSpec(
        "assistant",
        "Telegram guest assistant (parents, applicants): public knowledge only.",
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.CHAT_SUMMARY: TaskSpec(
        "assistant", "Short summary of the older messages of a long assistant chat."
    ),
    AiTask.CONTEXT_COMPACT: TaskSpec(
        "assistant",
        "Context compaction: a short summary of the older turns of a long notebook "
        "chat, cached per chat so it is not made again each turn. The cheapest model.",
        model=COMPACT_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.NOTEBOOK_CHAT: TaskSpec(
        "notebooks",
        "Grounded notebook chat (answers with citations).",
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.SOURCE_GUIDE: TaskSpec(
        "notebooks",
        "Source guide: summary, key topics and questions of one source.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.SOURCE_VISION_EXTRACT: TaskSpec(
        "notebooks",
        "Reads a scanned PDF or an image with no text layer (re-read of a source).",
        data_collection=_PRIVATE,
        model=SMART_MODEL,
        budget_weight=SMART_BUDGET_WEIGHT,
        reasoning_effort=SMART_REASONING,
    ),
    AiTask.NOTEBOOK_SUMMARY: TaskSpec(
        "notebooks",
        "Summary and key topics of a whole notebook.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.SOURCE_LABELS: TaskSpec(
        "notebooks",
        "Auto labels: topic labels of a notebook's sources and which source gets "
        "which (titles, key topics and short summaries only).",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_REPORT: TaskSpec(
        "notebooks",
        "Studio report or conspect (Markdown).",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_MIND_MAP: TaskSpec(
        "notebooks",
        "Studio mind map.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_FLASHCARDS: TaskSpec(
        "notebooks",
        "Studio flash cards.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_QUIZ: TaskSpec(
        "notebooks",
        "Studio quiz.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_DATA_TABLE: TaskSpec(
        "notebooks",
        "Studio data table.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_SLIDES: TaskSpec(
        "notebooks",
        "Studio slide deck.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_SLIDES_REVISE: TaskSpec(
        "notebooks",
        "Revision of some slides of a deck (no sources, only the deck).",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_INFOGRAPHIC: TaskSpec(
        "notebooks",
        "Studio infographic.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_EXERCISE: TaskSpec(
        "notebooks",
        "Studio exercise: a practice set (IELTS, SAT, AP style) with an original "
        "passage written from the sources and questions of several types.",
        data_collection=_PRIVATE,
        model=NOTEBOOK_MODEL,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.EXERCISE_FEEDBACK: TaskSpec(
        "notebooks",
        "Feedback on a student's essay or free response of a Studio exercise, "
        "against its rubric (the task, the rubric and the answer are sent); the "
        "student asks for it explicitly.",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.LMS_AUTHORING: TaskSpec(
        "lms", "The course author assistant (lms_author chats in a course workspace)."
    ),
    AiTask.WEB_SEARCH: TaskSpec(
        "search",
        "Web search for a chat message: one Exa search, no model call (only the "
        "question is sent to Exa). The task keeps its name for the quota and budgets.",
    ),
    AiTask.DISCOVER: TaskSpec(
        "search",
        "Discover sources: the plan of a deep run (its queries) and the ranking with "
        "one-line reasons of the pages Exa found. The searches are Exa's, not model "
        "calls; the model call uses the default model.",
        data_collection=_PRIVATE,
    ),
    AiTask.SUBJECT_TRANSLATE: TaskSpec(
        "academic",
        "Subject names: translates the missing uz, ru or en names of an EMIS subject "
        "from the names it has (only the names are sent, no personal data).",
        model=TRANSLATE_MODEL,
    ),
    AiTask.EMBEDDING: TaskSpec(
        "retrieval",
        "Embeddings: vectors of passages and questions for search by meaning "
        "(FEATURES__VECTOR_SEARCH). Not a chat model: temperature and fallbacks do "
        "not apply, because vectors of two models cannot be compared.",
        model=EMBEDDING_MODEL,
        data_collection=_PRIVATE,
        dimensions=EMBEDDING_DIMENSIONS,
        batch_size=EMBEDDING_BATCH_SIZE,
        query_prefix=EMBEDDING_QUERY_PREFIX,
    ),
    AiTask.RETRIEVAL_PLAN: TaskSpec(
        "notebooks",
        "Multi-hop retrieval: whether the passages found for a notebook chat "
        "question suffice, and follow-up queries for what is missing.",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.QUERY_DECOMPOSE: TaskSpec(
        "notebooks",
        "Query decomposition: splits a complex notebook chat question into "
        "sub-questions that are retrieved one by one (only the question is sent).",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_FAITHFULNESS: TaskSpec(
        "notebooks",
        "Faithfulness check of a Studio output against its sources.",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_SOURCE_PROFILE: TaskSpec(
        "notebooks",
        "Quiz and flash card planning: what each selected source is (vocabulary "
        "list, problem set, reading passages...), its subject and domains (the "
        "beginning of each source is sent).",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_ASSESSMENT_PLAN: TaskSpec(
        "notebooks",
        "Quiz and flash card blueprint: one slot per item (template, domain, "
        "difficulty, source); code keeps the exact count and the template quota.",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.STUDIO_ITEM_VERIFY: TaskSpec(
        "notebooks",
        "Quiz and flash card self-check: solves each item without the sources and "
        "rejects items that need unseen text or have no single answer.",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.WEB_MATERIAL_TRIAGE: TaskSpec(
        "notebooks",
        "Web materials triage: keeps only the substantive educational files and images "
        "linked from a web source (title, URL, nearby text; images are looked at).",
        model=CHEAP_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.OPENUI_REPAIR: TaskSpec(
        "assistant",
        "Fixes an OpenUI block of a chat answer that failed validation (the block "
        "and its errors only); a tiny coder model, a small answer, no reasoning.",
        model=OPENUI_REPAIR_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
    AiTask.MEDIA_DESCRIBE: TaskSpec(
        "notebooks",
        "Media reading: describes a gathered image and transcribes gathered audio so "
        "they can be searched and cited (a vision and audio model).",
        model=MEDIA_MODEL,
        data_collection=_PRIVATE,
        reasoning_effort=_NO_REASONING,
    ),
}

NOTEBOOK_TASKS: Final = frozenset(
    task for task, spec in TASK_SPECS.items() if spec.group == "notebooks"
)
# Notebook tasks that were the "light" model before tasks existed.
LIGHT_NOTEBOOK_TASKS: Final = frozenset(
    {AiTask.SOURCE_GUIDE, AiTask.NOTEBOOK_SUMMARY, AiTask.SOURCE_LABELS}
)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """The model and parameters one task runs with (see `Settings.ai_profile`)."""

    task: AiTask
    model: str
    temperature: float
    max_output_tokens: int | None  # None: the call site's own size
    reasoning_effort: ReasoningEffort | None
    fallbacks: tuple[str, ...]
    data_collection: DataCollection | None
    provider_order: tuple[str, ...]
    budget_weight: int
    # The kinds of input the model reads; a source of another kind is not sent to it.
    modalities: tuple[Modality, ...] = ALL_MODALITIES
    # Embedding tasks only; the values of any other task are unused.
    dimensions: int = EMBEDDING_DIMENSIONS
    batch_size: int = EMBEDDING_BATCH_SIZE
    query_prefix: str = ""
    document_prefix: str = ""

    @property
    def tuning(self) -> LlmTuning:
        """The part of the profile the gateway needs besides the model."""
        return LlmTuning(
            temperature=self.temperature,
            reasoning_effort=self.reasoning_effort,
            fallbacks=self.fallbacks,
            task=self.task.value,
        )

    def output_tokens(self, default: int) -> int:
        """The configured output limit, or the call site's own `default`."""
        return self.max_output_tokens or default

    def provider(self, **extra: Any) -> dict[str, Any] | None:  # OpenRouter's object
        """The OpenRouter `provider` routing object, or None when nothing is set.

        `extra` adds call-specific keys, e.g. `require_parameters=True`.
        """
        routing: dict[str, Any] = dict(extra)
        if self.data_collection is not None:
            routing["data_collection"] = self.data_collection
        if self.provider_order:
            routing["order"] = list(self.provider_order)
        return routing or None
