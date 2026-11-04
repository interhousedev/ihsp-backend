"""ADM-PHOTO-2, ADM-PHOTO-1: the group photo ZIP and the student list photo link."""

import dataclasses
import io
import uuid
import zipfile

from app.shared.actor import Role
from tests.academic.schedule.conftest import Api
from tests.academic.schedule.env import Env

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes"


async def test_an_admin_downloads_the_group_photos_as_a_zip(env: Env, api: Api) -> None:
    """ADM-PHOTO-2: GET /v1/admin/groups/{id}/photos.zip with counts in the headers."""
    group = await env.group("2TN2")
    ivan = await env.student(group, first_name="Ivan", last_name="Ivanov")
    await env.student(group, first_name="Petr", last_name="Petrov")
    file_id = env.files.add(JPEG)
    env.identity.add(
        dataclasses.replace(env.identity.users[ivan.id], photo_file_id=file_id)
    )

    response = await api.client.get(f"/v1/admin/groups/{group.id}/photos.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-photos-exported"] == "1"
    assert response.headers["x-photos-missing"] == "1"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.read("Ivanov Ivan.jpg") == JPEG
    assert "Petrov Petr" in archive.read("manifest.txt").decode("utf-8")


async def test_a_curator_who_is_not_an_admin_gets_403(env: Env, api: Api) -> None:
    """ADM-PHOTO-2: the export is for administrators only."""
    group = await env.group("2TN2")
    api.as_role(Role.TEACHER)

    response = await api.client.get(f"/v1/admin/groups/{group.id}/photos.zip")

    assert response.status_code == 403
    assert response.json()["type"] == "common/forbidden"


async def test_an_unknown_group_answers_404(env: Env, api: Api) -> None:
    """ADM-PHOTO-2: a missing group is not found."""
    response = await api.client.get(f"/v1/admin/groups/{uuid.uuid4()}/photos.zip")

    assert response.status_code == 404


async def test_the_student_list_carries_the_photo_link(env: Env, api: Api) -> None:
    """ADM-PHOTO-1: the admin dialog shows the current photo of each student."""
    group = await env.group("2TN2")
    ivan = await env.student(group, first_name="Ivan", last_name="Ivanov")
    await env.student(group, first_name="Petr", last_name="Petrov")
    env.identity.photos[ivan.id] = "https://files.test/ivan.jpg"

    response = await api.client.get("/v1/admin/students")

    items = {item["first_name"]: item for item in response.json()["items"]}
    assert items["Ivan"]["photo_url"] == "https://files.test/ivan.jpg"
    assert items["Petr"]["photo_url"] is None
