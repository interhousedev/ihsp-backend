"""Uploading H5P packages and launching a draft's package in the editor."""

import io
import json
import zipfile
from uuid import UUID

from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    H5PBlockNotFoundError,
    H5PPackageInvalidError,
)
from app.modules.lms.domain.h5p_token import package_prefix
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


GOOD = _zip(
    {
        "h5p.json": json.dumps({"title": "Q", "mainLibrary": "H5P.Blanks"}).encode(),
        "content/content.json": b"{}",
        "H5P.Blanks-1.14/js/blanks.js": b"var x;",
    }
)


async def test_a_package_is_stored_under_the_course_and_launched(
    services: AuthoringServices, course: CourseFixture
) -> None:
    owner = course.team.owner
    view = await services.upload_h5p.execute(owner, course.id, GOOD)
    store = services.upload_h5p.store
    assert isinstance(store, MemoryH5PStore)
    prefix = package_prefix(course.id, UUID(view.package_id))
    assert set(store.objects) == {
        prefix + "h5p.json",
        prefix + "content/content.json",
        prefix + "H5P.Blanks-1.14/js/blanks.js",
    }
    assert (view.title, view.main_library, view.files) == ("Q", "H5P.Blanks", 3)

    seeded = await seed_published(services, owner, course.id)
    block = {"id": "", "type": "h5p", "package_id": view.package_id}
    draft = await set_blocks(services, owner, seeded.step_a, block)
    block_id = draft.content.blocks[0].id
    launch = await services.preview_h5p.execute(
        course.team.tester, course.id, draft.step_id, block_id
    )
    assert launch.base_url.startswith("/v1/lms/h5p/") and launch.expires_in > 0
    with pytest.raises(H5PBlockNotFoundError):
        await services.preview_h5p.execute(owner, course.id, draft.step_id, "nope")


async def test_bad_packages_and_people_without_edit_are_refused(
    services: AuthoringServices, course: CourseFixture
) -> None:
    with pytest.raises(H5PPackageInvalidError) as caught:
        await services.upload_h5p.execute(
            course.team.owner, course.id, _zip({"../x.js": b""})
        )
    assert caught.value.params["reason"] == "unsafe-path"
    with pytest.raises(CoursePermissionError):
        await services.upload_h5p.execute(course.team.tester, course.id, GOOD)
