"""G12/G31: topic labels in a course workspace: editors write, readers only read."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks import ROUTERS
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    WorkspaceReadOnlyError,
)
from app.modules.notebooks.domain.labels import LabelRunStatus
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from tests.fakes.tasks import FakeTaskKicker

import pytest
from httpx import AsyncClient


@pytest.fixture
async def api(
    http_client: Any, services: NotebooksServices, teacher: Actor
) -> AsyncClient:
    """A client of the notebook routes; set `api.actor` to change the caller."""
    current = {"actor": teacher}
    client: AsyncClient = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, notebooks=services
    )
    client.actor = current  # type: ignore[attr-defined]
    return client


async def test_a_viewer_reads_the_labels_but_cannot_change_them(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: Source,
    teacher: Actor,
    viewer: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """G31: `view_drafts` lists labels; every write is `workspace-readonly`."""
    label = await services.create_label.execute(teacher, workspace.id, "Laws", "⚖️")

    listing = await services.list_labels.execute(viewer, workspace.id)

    assert [x.name for x in listing.items] == ["Laws"]
    writes = [
        services.create_label.execute(viewer, workspace.id, "More", "⚖️"),
        services.update_label.execute(viewer, workspace.id, label.id, {"name": "X"}),
        services.delete_label.execute(viewer, workspace.id, label.id),
        services.set_source_labels.execute(viewer, workspace.id, ws_source.id, []),
        services.start_labeling.execute(viewer, workspace.id),
    ]
    for write in writes:
        with pytest.raises(WorkspaceReadOnlyError):
            await write
    assert kicker.calls == []
    assert (await services.list_labels.execute(teacher, workspace.id)).items[0].id == (
        label.id
    )


async def test_a_stranger_gets_a_404_for_labels(
    services: NotebooksServices, workspace: Notebook, stranger: Actor
) -> None:
    """G31: a teacher who is not on the course staff sees no workspace."""
    with pytest.raises(NotebookNotFoundError):
        await services.list_labels.execute(stranger, workspace.id)
    with pytest.raises(NotebookNotFoundError):
        await services.create_label.execute(stranger, workspace.id, "Laws", "⚖️")


async def test_an_editor_labels_the_workspace_and_the_editor_pays(
    services: NotebooksServices,
    workspace: Notebook,
    ws_source: Source,
    editor: Actor,
    kicker: FakeTaskKicker,
) -> None:
    """G31: a second editor starts the run; the run remembers who clicked."""
    run = await services.start_labeling.execute(editor, workspace.id)

    assert run.status is LabelRunStatus.RUNNING and run.started_by == editor.user_id
    assert kicker.names() == ["notebooks.label_sources"]


async def test_the_routes_follow_the_same_rules(
    api: AsyncClient,
    workspace: Notebook,
    ws_source: Source,
    viewer: Actor,
    editor: Actor,
) -> None:
    """G31: 200/201 for editors; 403 `workspace-readonly` for a reader's writes."""
    base = f"/v1/notebooks/{workspace.id}"
    created = await api.post(f"{base}/labels", json={"name": "Laws", "emoji": "⚖️"})
    api.actor["actor"] = viewer  # type: ignore[attr-defined]

    read = await api.get(f"{base}/labels")
    refused = await api.post(f"{base}/labels", json={"name": "More", "emoji": ""})
    auto = await api.post(f"{base}/labels/auto")

    assert (created.status_code, read.status_code) == (201, 200)
    assert [refused.status_code, auto.status_code] == [403, 403]
    assert refused.json()["type"] == "notebooks/workspace-readonly"
