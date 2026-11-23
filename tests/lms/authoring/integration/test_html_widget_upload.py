"""Uploading HTML widgets and launching a draft's widget in the editor."""

import io
import zipfile
from uuid import UUID

from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    HtmlWidgetBlockNotFoundError,
    HtmlWidgetInvalidError,
)
from app.modules.lms.domain.html_widget import widget_prefix
from app.modules.lms.infrastructure.h5p_memory_store import MemoryH5PStore
from app.modules.lms.wiring_authoring import AuthoringServices
from tests.lms.authoring.conftest import CourseFixture
from tests.lms.authoring.helpers import seed_published, set_blocks

import pytest


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


GOOD = _zip({"index.html": b"<p>hi</p>", "js/app.js": b"1;", "img/a.svg": b"<svg/>"})


async def test_a_widget_is_stored_under_the_course_and_launched(
    services: AuthoringServices, course: CourseFixture
) -> None:
    owner = course.team.owner
    view = await services.upload_html_widget.execute(owner, course.id, GOOD, "w.zip")
    store = services.upload_html_widget.store
    assert isinstance(store, MemoryH5PStore)
    prefix = widget_prefix(course.id, UUID(view.package_id))
    assert {key for key in store.objects if key.startswith(prefix)} == {
        prefix + "index.html",
        prefix + "js/app.js",
        prefix + "img/a.svg",
    }
    assert view.file_count == 3
    assert [file.path for file in view.files] == [
        "img/a.svg",
        "index.html",
        "js/app.js",
    ]

    seeded = await seed_published(services, owner, course.id)
    block = {"id": "", "type": "html", "package_id": view.package_id}
    draft = await set_blocks(services, owner, seeded.step_a, block)
    block_id = draft.content.blocks[0].id
    launch = await services.preview_html_widget.execute(
        course.team.tester, course.id, draft.step_id, block_id
    )
    assert launch.entry_url.startswith("/v1/lms/html-widgets/")
    assert launch.entry_url.endswith("/index.html") and launch.expires_in > 0
    with pytest.raises(HtmlWidgetBlockNotFoundError):
        await services.preview_html_widget.execute(
            owner, course.id, draft.step_id, "nope"
        )


async def test_bad_widgets_and_people_without_edit_are_refused(
    services: AuthoringServices, course: CourseFixture
) -> None:
    with pytest.raises(HtmlWidgetInvalidError) as caught:
        await services.upload_html_widget.execute(
            course.team.owner, course.id, _zip({"../x.html": b""}), "w.zip"
        )
    assert caught.value.params["reason"] == "unsafe-path"
    with pytest.raises(CoursePermissionError):
        await services.upload_html_widget.execute(
            course.team.tester, course.id, GOOD, "w.zip"
        )
