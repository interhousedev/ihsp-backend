"""Background tasks of the files module: names, arguments, delegation."""

from types import SimpleNamespace
from uuid import uuid4

from app.interfaces.jobs import context
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.tasks.files.cleanup_expired import cleanup_expired
from app.interfaces.jobs.tasks.files.delete_owner import delete_owner
from app.interfaces.jobs.tasks.files.process import process
from app.interfaces.jobs.tasks.files.purge_pending import purge_pending
from app.interfaces.jobs.tasks.files.sweep_processing import sweep_processing
from app.interfaces.jobs.tasks.files.warn_expiring import warn_expiring
from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import upload_and_complete

import pytest


@pytest.fixture
def worker_container(
    fakes: FilesFakes, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    """What get_container() returns inside a worker."""
    container = SimpleNamespace(files=fakes.services)
    monkeypatch.setattr(context, "_container", container)
    return container


@pytest.mark.parametrize(
    "name",
    [
        "files.process",
        "files.cleanup_expired",
        "files.warn_expiring",
        "files.purge_pending",
        "files.sweep_processing",
        "files.delete_owner",
    ],
)
def test_every_task_is_registered_under_its_wire_name(name: str) -> None:
    """TaskKicker and the scheduler start tasks by these names."""
    assert broker.find_task(name) is not None


async def test_process_task_processes_the_file(
    fakes: FilesFakes, student: Actor, worker_container: SimpleNamespace
) -> None:
    """files.process(file_id) runs the processing step."""
    view = await upload_and_complete(
        fakes, student, name="a.txt", data=b"some text", content_type="text/plain"
    )

    await process(view.file.id)

    assert fakes.db.row(view.file.id).status == FileStatus.READY


async def test_cleanup_and_sweep_and_purge_and_warn_tasks_return_counts(
    worker_container: SimpleNamespace,
) -> None:
    """Housekeeping tasks return how many items they handled (zero on an empty db)."""
    assert await cleanup_expired() == 0
    assert await warn_expiring() == 0
    assert await purge_pending() == 0
    assert await sweep_processing() == 0


async def test_delete_owner_task_deletes_the_users_files(
    fakes: FilesFakes, student: Actor, worker_container: SimpleNamespace
) -> None:
    """files.delete_owner(user_id) removes everything of the user."""
    view = await upload_and_complete(
        fakes, student, name="a.txt", data=b"some text", content_type="text/plain"
    )

    deleted = await delete_owner(student.user_id)

    assert deleted == 1
    assert fakes.db.row(view.file.id).status == FileStatus.DELETED
    assert await delete_owner(uuid4()) == 0
