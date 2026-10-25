"""NB-14: the `EMBEDDING` AI task, its settings and its feature flag."""

from app.interfaces.jobs.schedule import CRON_JOBS, enabled_jobs
from app.settings import Settings
from app.settings_ai import AiSettings, AiTaskSettings
from app.shared.ai_tasks import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_QUERY_PREFIX,
    TASK_SPECS,
    AiTask,
)
from app.shared.db.embeddings import EMBEDDING_DIMS

import pytest


def test_the_profile_size_is_the_size_of_the_database_column() -> None:
    """A model that returns another size would not fit `halfvec(1024)`."""
    assert EMBEDDING_DIMENSIONS == EMBEDDING_DIMS == 1024


def test_the_default_profile_is_a_multilingual_private_embedding_model() -> None:
    """Qwen3 4B, 1024 numbers, 32 texts per request, the question gets a task line."""
    profile = AiSettings().profile(AiTask.EMBEDDING)

    assert profile.model == "qwen/qwen3-embedding-4b"
    assert profile.dimensions == 1024
    assert profile.batch_size == EMBEDDING_BATCH_SIZE == 32
    assert profile.query_prefix == EMBEDDING_QUERY_PREFIX
    assert profile.document_prefix == ""
    assert profile.provider() == {"data_collection": "deny"}
    assert TASK_SPECS[AiTask.EMBEDDING].group == "retrieval"


def test_the_default_chat_model_never_becomes_the_embedding_model() -> None:
    """`AI__DEFAULT__MODEL` is for chat; the task ships its own model."""
    ai = AiSettings.model_validate({"default": {"model": "x/chat-model"}})

    assert ai.profile(AiTask.EMBEDDING).model == "qwen/qwen3-embedding-4b"


def test_the_task_settings_change_model_size_batch_and_prefixes() -> None:
    """Switching to e5: its own prefixes and a bigger batch."""
    ai = AiSettings(
        tasks={
            AiTask.EMBEDDING: AiTaskSettings(
                model="intfloat/multilingual-e5-large",
                batch_size=64,
                query_prefix="query: ",
                document_prefix="passage: ",
            )
        }
    )

    profile = ai.profile(AiTask.EMBEDDING)

    assert profile.model == "intfloat/multilingual-e5-large"
    assert profile.batch_size == 64
    assert (profile.query_prefix, profile.document_prefix) == ("query: ", "passage: ")
    assert profile.dimensions == 1024


def test_none_removes_the_built_in_query_line() -> None:
    """A model without instructions (bge-m3): `QUERY_PREFIX=none`."""
    ai = AiSettings(tasks={AiTask.EMBEDDING: AiTaskSettings(query_prefix="none")})

    assert ai.profile(AiTask.EMBEDDING).query_prefix == ""


def test_the_environment_reaches_the_embedding_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IHSP_AI__TASKS__EMBEDDING__*."""
    monkeypatch.setenv("IHSP_AI__TASKS__EMBEDDING__MODEL", "baai/bge-m3")
    monkeypatch.setenv("IHSP_AI__TASKS__EMBEDDING__QUERY_PREFIX", "none")
    monkeypatch.setenv("IHSP_AI__TASKS__EMBEDDING__BATCH_SIZE", "16")

    profile = Settings().ai_profile(AiTask.EMBEDDING)

    assert (profile.model, profile.query_prefix, profile.batch_size) == (
        "baai/bge-m3",
        "",
        16,
    )


def test_vector_search_is_on_by_default_with_bounded_jobs() -> None:
    """The flag and the limits that keep the cost small."""
    settings = Settings()

    assert settings.features.vector_search is True
    assert settings.vectors.daily_token_budget == 20_000_000
    assert settings.vectors.backfill_texts_per_run == 256
    assert settings.vectors.query_timeout_seconds == 2.5


def test_the_backfill_runs_every_ten_minutes_and_follows_the_feature() -> None:
    """The cron entry exists and disappears with FEATURES__VECTOR_SEARCH=false."""
    names = {job.task_name: job.cron for job in CRON_JOBS}
    off = Settings(features={"vector_search": False})  # type: ignore[arg-type]

    assert names["notebooks.embed_passages"] == "*/10 * * * *"
    kept = {job.task_name for job in enabled_jobs(off)}
    assert "notebooks.embed_passages" not in kept
    assert "notebooks.refresh_summaries" in kept  # notebooks itself stays on
    assert "notebooks.embed_passages" in {
        job.task_name for job in enabled_jobs(Settings())
    }
