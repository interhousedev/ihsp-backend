"""A Studio request with thin sources suggests a web search; nothing is searched."""

from datetime import UTC, datetime
from uuid import UUID

from app.interfaces.http.v1.notebooks.schemas_studio import ArtifactItemResponse
from app.modules.notebooks.domain.entities import Artifact, Notebook
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.web_suggestion import suggestion_for_request
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_source
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import SOURCE_TEXTS

LONG_TEXT = "photosynthesis converts light into chemical energy " * 200  # ~10k chars


async def test_thin_sources_suggest_a_query_from_topic_and_focus(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
) -> None:
    """Short sources give the suggestion; the job is still queued, not a search."""
    await make_source(uow_factory, notebook, texts=("one short note",))

    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, "cell respiration"
    )

    assert artifact.suggest_web_search is not None
    assert notebook.title in artifact.suggest_web_search
    assert "cell respiration" in artifact.suggest_web_search
    assert kicker.calls != []


async def test_full_sources_suggest_nothing(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """Enough source text (above the default threshold): no suggestion."""
    await make_source(uow_factory, notebook, texts=(LONG_TEXT,))

    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    assert artifact.suggest_web_search is None


async def test_no_sources_suggest_a_search(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """A request made without any selected source is thin by definition."""
    await make_source(uow_factory, notebook, texts=SOURCE_TEXTS, selected=False)

    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    assert artifact.suggest_web_search is not None
    assert notebook.title in artifact.suggest_web_search


def test_create_response_carries_the_suggestion_object() -> None:
    """The field is `suggest_web_search: {query}`; null when there is none."""
    now = datetime(2026, 10, 1, tzinfo=UTC)
    row = Artifact(
        id=UUID(int=1),
        notebook_id=UUID(int=2),
        owner_id=UUID(int=3),
        kind=ArtifactKind.QUIZ,
        title="Quiz",
        created_at=now,
        updated_at=now,
        status=ArtifactStatus.QUEUED,
        suggest_web_search="Biology",
    )
    dumped = ArtifactItemResponse.from_entity(row).model_dump(mode="json")
    assert dumped["suggest_web_search"] == {"query": "Biology"}

    row.suggest_web_search = None
    dumped = ArtifactItemResponse.from_entity(row).model_dump(mode="json")
    assert dumped["suggest_web_search"] is None


def test_zero_threshold_never_suggests_for_text() -> None:
    """A threshold of 0 disables the text rule (only a missing source is thin)."""
    assert (
        suggestion_for_request(char_counts=[10], title="Bio", focus=None, threshold=0)
        is None
    )
