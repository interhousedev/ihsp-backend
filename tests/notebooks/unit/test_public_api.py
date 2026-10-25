"""NB-17, NB-14, FILE-6: the public queries and commands the assistant and files use."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.public_api import (
    NotebooksQueriesImpl,
    SourcePageNotFoundError,
)
from app.modules.notebooks.application.public_commands import NotebooksCommandsImpl
from app.modules.notebooks.application.views import AddSourcesResult, RejectedSource
from app.modules.notebooks.domain.entities import (
    Artifact,
    Notebook,
    NotebookSummary,
    Source,
)
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    SourceKind,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    SourceDuplicateError,
    SourceNotReadyError,
)
from app.modules.notebooks.domain.source_input import SourceInput
from app.modules.notebooks.domain.text_pages import PAGE_BYTES
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import (
    NOW,
    make_artifact,
    make_notebook,
    make_source,
    new_artifact_entity,
    new_notebook_entity,
    new_source_entity,
)

import pytest


@pytest.fixture
def queries(uow_factory: UowFactory, core: NotebooksCore) -> NotebooksQueriesImpl:
    """The public queries over the SQL unit of work and the quota service."""
    return NotebooksQueriesImpl(uow_factory, core.quota)


# - - - list_notebooks - - -


async def test_list_notebooks_returns_json_rows_of_the_owner_only(
    uow_factory: UowFactory,
    queries: NotebooksQueriesImpl,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-17: ids are strings, counts and the last opened time are present."""
    mine = await make_notebook(
        uow_factory, student.user_id, title="Biology", emoji="🧬", last_opened_at=NOW
    )
    await make_source(uow_factory, mine)
    await make_source(uow_factory, mine)
    await make_notebook(uow_factory, other_student.user_id, title="Secret")
    await make_notebook(uow_factory, student.user_id, title="Gone", deleted_at=NOW)

    rows = await queries.list_notebooks(student.user_id)

    assert [r["title"] for r in rows] == ["Biology"]
    row = rows[0]
    assert row["id"] == str(mine.id)
    assert (row["emoji"], row["source_count"]) == ("🧬", 2)
    assert str(row["last_opened_at"]).startswith("2026-10-06T09:00:00")


async def test_list_notebooks_respects_the_limit(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: the limit caps the rows."""
    for number in range(3):
        await make_notebook(uow_factory, student.user_id, title=f"N{number}")

    rows = await queries.list_notebooks(student.user_id, limit=2)

    assert len(rows) == 2


# - - - get_notebook - - -


async def test_get_notebook_returns_summary_topics_and_sources(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: title, summary text, key topics and every source with its words."""
    summary = NotebookSummary(
        summary="Cells and energy.", key_topics=["cell", "ATP"], generated_at=NOW
    )
    notebook = await make_notebook(
        uow_factory,
        student.user_id,
        summary=summary,
        summary_status=SummaryStatus.READY,
    )
    ready = await make_source(
        uow_factory,
        notebook,
        title="Cells.pdf",
        kind=SourceKind.FILE,
        texts=("one two three", "four five"),
    )
    pending = await make_source(
        uow_factory, notebook, title="Later", status=SourceStatus.PENDING, texts=()
    )

    found = await queries.get_notebook(student.user_id, notebook.id)

    assert found is not None
    assert (found["id"], found["title"]) == (str(notebook.id), "Biology")
    assert (found["summary"], found["key_topics"]) == (
        "Cells and energy.",
        ["cell", "ATP"],
    )
    assert found["sources"] == [
        {
            "id": str(ready.id),
            "title": "Cells.pdf",
            "kind": "file",
            "status": "ready",
            "words": 5,
            "selected": True,
        },
        {
            "id": str(pending.id),
            "title": "Later",
            "kind": "text",
            "status": "pending",
            "words": 0,
            "selected": True,
        },
    ]


async def test_get_notebook_without_a_summary_has_empty_fields(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: a fresh notebook has no summary and no topics yet."""
    notebook = await make_notebook(uow_factory, student.user_id)

    found = await queries.get_notebook(student.user_id, notebook.id)

    assert found is not None
    assert (found["summary"], found["key_topics"], found["sources"]) == (None, [], [])


async def test_get_notebook_is_none_for_other_owners_deleted_and_unknown(
    uow_factory: UowFactory,
    queries: NotebooksQueriesImpl,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-17: another student's, a deleted and a missing notebook are all None."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    deleted = await make_notebook(uow_factory, student.user_id, deleted_at=NOW)

    assert await queries.get_notebook(student.user_id, theirs.id) is None
    assert await queries.get_notebook(student.user_id, deleted.id) is None
    assert await queries.get_notebook(student.user_id, new_id()) is None


# - - - search - - -


async def test_search_returns_passages_with_their_source_and_ranked(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17, NB-14: the passage matching more of the query comes first."""
    notebook = await make_notebook(uow_factory, student.user_id)
    both = "The mitochondria is the powerhouse of the cell."
    one = "Mitochondria are organelles with two membranes."
    source = await make_source(
        uow_factory, notebook, title="Cells.pdf", texts=(one, "Unrelated text.", both)
    )

    found = await queries.search(
        student.user_id, notebook.id, "mitochondria powerhouse"
    )

    assert [p["text"] for p in found] == [both, one]
    assert found[0] == {
        "source_id": str(source.id),
        "source_title": "Cells.pdf",
        "seq": 3,
        "page": None,
        "text": both,
    }


async def test_search_uses_only_usable_sources_and_caps_the_text(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: failed and pending sources are skipped; a passage is cut at 600."""
    notebook = await make_notebook(uow_factory, student.user_id)
    long_text = "Mitochondria " + "word " * 300
    await make_source(uow_factory, notebook, title="Long", texts=(long_text,))
    await make_source(
        uow_factory,
        notebook,
        title="Stale",
        status=SourceStatus.STALE,
        texts=("Mitochondria again.",),
    )
    await make_source(
        uow_factory,
        notebook,
        title="Failed",
        status=SourceStatus.FAILED,
        texts=("Mitochondria hidden.",),
    )

    found = await queries.search(student.user_id, notebook.id, "mitochondria")

    assert sorted(p["source_title"] for p in found) == ["Long", "Stale"]
    assert max(len(p["text"]) for p in found) == 600


async def test_search_of_another_students_notebook_finds_nothing(
    uow_factory: UowFactory,
    queries: NotebooksQueriesImpl,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-17: ownership is checked; the other student's text never leaks."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, theirs, texts=("Secret mitochondria.",))

    found = await queries.search(student.user_id, theirs.id, "mitochondria")
    nothing = await queries.search(student.user_id, new_id(), "mitochondria")

    assert found == [] and nothing == []


async def test_search_limit_caps_the_rows(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: `limit` bounds the passages; 0 and negative values mean at least one."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(
        uow_factory,
        notebook,
        texts=tuple(f"Cell number {n} divides." for n in range(5)),
    )

    two = await queries.search(student.user_id, notebook.id, "divides", limit=2)
    floor = await queries.search(student.user_id, notebook.id, "divides", limit=0)

    assert len(two) == 2 and len(floor) == 1


# - - - read_source_page - - -


async def test_read_source_page_returns_the_passages_joined_by_a_blank_line(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: a short source is one page with its passages in order."""
    notebook = await make_notebook(uow_factory, student.user_id)
    source = await make_source(
        uow_factory, notebook, title="Notes", texts=("First.", "Second.")
    )

    page = await queries.read_source_page(student.user_id, notebook.id, source.id, 1)

    assert page == {
        "source_id": str(source.id),
        "title": "Notes",
        "page": 1,
        "pages": 1,
        "text": "First.\n\nSecond.",
    }


async def test_read_source_page_splits_long_text_at_whitespace_in_8_kb_pages(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: pages hold at most 8192 UTF-8 bytes and join back to the full text."""
    notebook = await make_notebook(uow_factory, student.user_id)
    texts = tuple(("Фотосинтез " * 150).strip() + f" {n}." for n in range(12))
    source = await make_source(uow_factory, notebook, texts=texts)
    whole = "\n\n".join(texts)

    first = await queries.read_source_page(student.user_id, notebook.id, source.id, 1)
    pages = [
        await queries.read_source_page(student.user_id, notebook.id, source.id, n)
        for n in range(1, first["pages"] + 1)
    ]

    assert first["pages"] > 1
    assert all(len(p["text"].encode()) <= PAGE_BYTES for p in pages)
    assert "".join(p["text"] for p in pages) == whole
    assert all(p["text"].endswith((" ", "\n")) for p in pages[:-1])


@pytest.mark.parametrize("page", [0, -1, 2])
async def test_read_source_page_outside_the_text_is_a_404(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor, page: int
) -> None:
    """NB-17: a page that does not exist raises a 404 error like read_file."""
    notebook = await make_notebook(uow_factory, student.user_id)
    source = await make_source(uow_factory, notebook)

    with pytest.raises(SourcePageNotFoundError) as caught:
        await queries.read_source_page(student.user_id, notebook.id, source.id, page)

    assert caught.value.status == 404
    assert caught.value.params == {"page": page, "pages": 1}


async def test_read_source_page_of_foreign_or_mismatched_sources_is_not_found(
    uow_factory: UowFactory,
    queries: NotebooksQueriesImpl,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-17: another owner's source, a source of another notebook, unknown ids."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    foreign = await make_source(uow_factory, theirs)
    mine = await make_notebook(uow_factory, student.user_id)
    other_mine = await make_notebook(uow_factory, student.user_id)
    own = await make_source(uow_factory, mine)

    for notebook_id, source_id in (
        (theirs.id, foreign.id),
        (mine.id, foreign.id),
        (other_mine.id, own.id),
        (mine.id, new_id()),
        (new_id(), own.id),
    ):
        with pytest.raises(NotebookNotFoundError):
            await queries.read_source_page(student.user_id, notebook_id, source_id, 1)


async def test_read_source_page_of_a_source_that_is_not_ready_is_refused(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: a pending source has no text yet."""
    notebook = await make_notebook(uow_factory, student.user_id)
    source = await make_source(
        uow_factory, notebook, status=SourceStatus.PENDING, texts=()
    )

    with pytest.raises(SourceNotReadyError):
        await queries.read_source_page(student.user_id, notebook.id, source.id, 1)


# - - - list_artifacts - - -


async def test_list_artifacts_returns_kind_title_and_status(
    uow_factory: UowFactory, queries: NotebooksQueriesImpl, student: Actor
) -> None:
    """NB-17: the notebook's outputs without their content; deleted ones are hidden."""
    notebook = await make_notebook(uow_factory, student.user_id)
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ, title="Quiz 1")
    queued = await make_artifact(
        uow_factory, notebook, ArtifactKind.REPORT, ArtifactStatus.QUEUED
    )
    await make_artifact(uow_factory, notebook, deleted_at=NOW)

    rows = await queries.list_artifacts(student.user_id, notebook.id)

    assert {r["id"]: (r["kind"], r["title"], r["status"]) for r in rows} == {
        str(quiz.id): ("quiz", "Quiz 1", "ready"),
        str(queued.id): ("report", "Report", "queued"),
    }


async def test_list_artifacts_of_another_students_notebook_is_empty(
    uow_factory: UowFactory,
    queries: NotebooksQueriesImpl,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-17: ownership is checked."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await make_artifact(uow_factory, theirs)

    assert await queries.list_artifacts(student.user_id, theirs.id) == []
    assert await queries.list_artifacts(student.user_id, new_id()) == []


# - - - used_by_files - - -


async def test_used_by_files_lists_the_notebooks_that_hold_a_file(
    uow_factory: UowFactory,
    queries: NotebooksQueriesImpl,
    student: Actor,
    other_student: Actor,
) -> None:
    """FILE-6: (kind, notebook id, title) per file, deleted notebooks skipped."""
    file_id, unused = new_id(), new_id()
    first = await make_notebook(uow_factory, student.user_id, title="Biology")
    second = await make_notebook(uow_factory, other_student.user_id, title="Chemistry")
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=NOW)
    for notebook in (first, second, gone):
        await make_source(
            uow_factory,
            notebook,
            kind=SourceKind.FILE,
            ref={"file_id": str(file_id)},
            ref_key=f"file:{file_id}",
        )

    used = await queries.used_by_files([file_id, unused])

    assert set(used) == {file_id}
    assert sorted(used[file_id], key=lambda t: t[2]) == [
        ("notebook", first.id, "Biology"),
        ("notebook", second.id, "Chemistry"),
    ]


async def test_used_by_files_without_files_is_empty(
    queries: NotebooksQueriesImpl,
) -> None:
    """FILE-6: nothing to ask, nothing to answer."""
    assert await queries.used_by_files([]) == {}


# - - - usage - - -


async def test_usage_counts_the_outputs_requested_today(
    queries: NotebooksQueriesImpl, core: NotebooksCore, student: Actor
) -> None:
    """NB-14, NB-17: the totals and the slides counter come from the quota service."""
    fresh = await queries.usage(student.user_id)
    await core.quota.reserve(student.user_id, ArtifactKind.REPORT, new_id())
    await core.quota.reserve(student.user_id, ArtifactKind.SLIDES, new_id())

    after = await queries.usage(student.user_id)

    limit = core.deps.settings.limits.nb_artifacts_per_day
    assert set(fresh) == {"artifacts", "audio_overview", "slides", "infographic"}
    assert (fresh["artifacts"]["used"], fresh["artifacts"]["limit"]) == (0, limit)
    assert (after["artifacts"]["used"], after["slides"]["used"]) == (2, 1)
    assert after["infographic"]["used"] == 0
    assert isinstance(after["artifacts"]["resets_at"], str)


# - - - commands (the use cases are stubbed) - - -


class StubCreateNotebook:
    """Records the title it was given and returns a notebook."""

    def __init__(self, owner: UUID) -> None:
        """Remember the owner of the notebook to return."""
        self.owner = owner
        self.calls: list[tuple[Actor, str | None, str | None]] = []

    async def execute(
        self, actor: Actor, title: str | None = None, emoji: str | None = None
    ) -> Notebook:
        """Return a notebook titled like the request (or the default)."""
        self.calls.append((actor, title, emoji))
        return new_notebook_entity(self.owner, title=title or "Untitled notebook")


class StubAddSources:
    """Returns a prepared result and records the parsed inputs."""

    def __init__(self, result: AddSourcesResult) -> None:
        """Keep the result to return."""
        self.result = result
        self.calls: list[tuple[UUID, list[SourceInput]]] = []

    async def execute(
        self, actor: Actor, notebook_id: UUID, items: Sequence[SourceInput]
    ) -> AddSourcesResult:
        """Record the call."""
        self.calls.append((notebook_id, list(items)))
        return self.result


class StubRequestArtifact:
    """Returns a queued output and records the request."""

    def __init__(self) -> None:
        """Start without calls."""
        self.calls: list[tuple[UUID, ArtifactKind, Mapping[str, Any], str | None]] = []

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        kind: ArtifactKind,
        options: Mapping[str, Any],
        prompt: str | None,
    ) -> Artifact:
        """Record the call and return a queued output."""
        self.calls.append((notebook_id, kind, options, prompt))
        notebook = new_notebook_entity(actor.user_id)
        return new_artifact_entity(
            notebook, kind=kind, status=ArtifactStatus.QUEUED, title="Quiz: Biology"
        )


def sources_made(count: int) -> list[Source]:
    """Pending sources of one notebook."""
    notebook = new_notebook_entity()
    return [
        new_source_entity(
            notebook, title=f"S{n}", status=SourceStatus.PENDING, position=n
        )
        for n in range(1, count + 1)
    ]


def commands_with(
    student: Actor, result: AddSourcesResult | None = None
) -> tuple[
    NotebooksCommandsImpl, StubCreateNotebook, StubAddSources, StubRequestArtifact
]:
    """Commands over stub use cases."""
    create = StubCreateNotebook(student.user_id)
    add = StubAddSources(result or AddSourcesResult())
    request = StubRequestArtifact()
    impl = NotebooksCommandsImpl(
        create_notebook=create, add_sources=add, request_artifact=request
    )
    return impl, create, add, request


async def test_create_notebook_adds_file_and_text_sources(student: Actor) -> None:
    """NB-17: the notebook is created, then the parsed sources are added."""
    file_id = new_id()
    items = sources_made(2)
    impl, create, add, _ = commands_with(student, AddSourcesResult(items=items))

    created = await impl.create_notebook(
        student,
        "Biology 10",
        [
            {"kind": "file", "file_id": str(file_id)},
            {"kind": "text", "title": "My notes", "text": "Cells."},
        ],
    )

    notebook_id, parsed = add.calls[0]
    assert create.calls == [(student, "Biology 10", None)]
    assert [(s.kind, getattr(s, "file_id", None)) for s in parsed] == [
        ("file", file_id),
        ("text", None),
    ]
    assert created == {
        "id": str(notebook_id),
        "title": "Biology 10",
        "added": 2,
        "rejected": [],
    }


async def test_create_notebook_reports_refused_sources_and_uses_the_default_title(
    student: Actor,
) -> None:
    """NB-17: an empty title becomes the default; refusals list index and type."""
    refused = AddSourcesResult(
        items=sources_made(1),
        rejected=[RejectedSource(1, SourceDuplicateError())],
    )
    impl, create, _, _ = commands_with(student, refused)

    created = await impl.create_notebook(
        student,
        "  ",
        [{"kind": "text", "title": "A", "text": "x"}] * 2,
    )

    assert create.calls[0][1] is None
    assert created["title"] == "Untitled notebook"
    assert (created["added"], created["rejected"]) == (
        1,
        [{"index": 1, "type": "notebooks/source-duplicate"}],
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "audio", "file_id": "x"},
        {"kind": "file"},
        {"kind": "file", "file_id": "not-a-uuid"},
        {"kind": "text", "title": "", "text": "x"},
        {"title": "no kind", "text": "x"},
    ],
)
async def test_create_notebook_checks_the_sources_before_storing_anything(
    student: Actor, bad: dict[str, Any]
) -> None:
    """NB-17: an unknown kind or a broken item is an invalid-options error."""
    impl, create, add, _ = commands_with(student)

    with pytest.raises(InvalidOptionsError):
        await impl.create_notebook(student, "Biology", [bad])

    assert create.calls == [] and add.calls == []


async def test_add_sources_returns_the_created_items(student: Actor) -> None:
    """NB-17: id, kind, title and status of every created source."""
    items = sources_made(2)
    impl, _, add, _ = commands_with(student, AddSourcesResult(items=items))
    notebook_id = new_id()

    created = await impl.add_sources(
        student,
        notebook_id,
        [
            {"kind": "text", "title": "A", "text": "x"},
            {"kind": "file", "file_id": str(new_id())},
        ],
    )

    assert add.calls[0][0] == notebook_id
    assert created == [
        {"id": str(s.id), "kind": "text", "title": s.title, "status": "pending"}
        for s in items
    ]


async def test_add_sources_raises_the_first_refusal_when_nothing_was_added(
    student: Actor,
) -> None:
    """NB-17: if every item is refused the assistant learns why."""
    refused = AddSourcesResult(rejected=[RejectedSource(0, SourceDuplicateError())])
    impl, _, _, _ = commands_with(student, refused)

    with pytest.raises(SourceDuplicateError):
        await impl.add_sources(
            student, new_id(), [{"kind": "text", "title": "A", "text": "x"}]
        )


async def test_add_sources_with_some_refusals_returns_only_the_created_ones(
    student: Actor,
) -> None:
    """NB-17: a partly refused batch is not an error."""
    partial = AddSourcesResult(
        items=sources_made(1), rejected=[RejectedSource(1, SourceDuplicateError())]
    )
    impl, _, _, _ = commands_with(student, partial)

    created = await impl.add_sources(
        student, new_id(), [{"kind": "text", "title": "A", "text": "x"}] * 2
    )

    assert len(created) == 1


async def test_request_artifact_passes_kind_options_and_prompt(student: Actor) -> None:
    """NB-17: the use case gets the enum, the options and the prompt as given."""
    impl, _, _, request = commands_with(student)
    notebook_id = new_id()

    queued = await impl.request_artifact(
        student, notebook_id, "quiz", {"count": "more"}, "Focus on cells"
    )

    assert request.calls == [
        (notebook_id, ArtifactKind.QUIZ, {"count": "more"}, "Focus on cells")
    ]
    assert set(queued) == {"id", "kind", "status"}
    assert (queued["kind"], queued["status"]) == ("quiz", "queued")


async def test_request_artifact_with_an_unknown_kind_is_invalid(student: Actor) -> None:
    """NB-17: kinds the build does not know are invalid options."""
    impl, _, _, request = commands_with(student)

    with pytest.raises(InvalidOptionsError):
        await impl.request_artifact(student, new_id(), "poem", {}, None)

    assert request.calls == []
