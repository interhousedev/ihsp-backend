"""HTTP routes of homework submissions."""

import datetime as dt

from tests.academic.classwork.conftest import Env
from tests.academic.classwork.test_http import client_as
from tests.academic.classwork.world import DAY, add_lesson
from tests.conftest import HttpClientFactory


async def test_submit_get_list_and_withdraw(
    env: Env, http_client: HttpClientFactory
) -> None:
    """PUT/GET/DELETE the submission; the teacher's list and the homework item."""
    lesson_id = await add_lesson(
        env.maker,
        env.world,
        homework_text="Read page 5",
        homework_due_date=DAY + dt.timedelta(days=1),
        homework_due_auto=False,
    )
    aziz = env.student("aziz")
    file_id = env.files.add(aziz.user_id)
    student = await client_as(http_client, env, aziz)
    teacher = await client_as(http_client, env, env.teacher)
    url = f"/v1/me/homework/{lesson_id}/submission"

    put = await student.put(url, json={"file_ids": [str(file_id)], "comment": "hi"})
    got = await student.get(url)
    items = [
        item
        for status in ("overdue", "upcoming", "later", "done")
        for item in (
            await student.get("/v1/me/homework", params={"status": status})
        ).json()
        if item["lesson_id"] == str(lesson_id)
    ]
    listed = await teacher.get(f"/v1/staff/lessons/{lesson_id}/homework/submissions")
    empty = await student.put(url, json={"file_ids": []})
    gone = await student.delete(url)
    after = await student.get(url)

    assert put.status_code == 200 and put.json()["status"] == "submitted"
    assert got.json()["files"][0]["id"] == str(file_id)
    assert items[0]["submission"]["file_count"] == 1
    assert listed.json()["counts"]["submitted"] == 1
    done = [r for r in listed.json()["students"] if r["status"] == "submitted"]
    assert done[0]["files"][0]["download_url"]
    assert empty.status_code == 422
    assert gone.status_code == 204
    assert after.status_code == 404
