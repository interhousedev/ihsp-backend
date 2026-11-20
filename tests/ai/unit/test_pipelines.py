"""Every AI task belongs to exactly one routing pipeline."""

from app.shared.ai_tasks import PIPELINE_OF, AiTask, Pipeline, pipeline_of


def test_every_task_has_a_pipeline() -> None:
    missing = [task for task in AiTask if task not in PIPELINE_OF]
    assert missing == []


def test_pipeline_of_returns_mapped_pipeline() -> None:
    assert pipeline_of(AiTask.STUDIO_QUIZ) is Pipeline.STUDIO
    assert pipeline_of(AiTask.EMBEDDING) is Pipeline.EMBEDDINGS
    assert pipeline_of(AiTask.VOICE_TRANSCRIBE) is Pipeline.VOICE


def test_pipeline_values_are_the_contract_names() -> None:
    assert {p.value for p in Pipeline} == {
        "chat",
        "notebooks",
        "studio",
        "admission",
        "teacher",
        "lms",
        "embeddings",
        "web_search",
        "voice",
        "utility",
    }
