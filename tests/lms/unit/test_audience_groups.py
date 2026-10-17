"""Unknown audience group ids are rejected through the group directory port."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.authoring.update_course_details import (
    UpdateCourseDetails,
)
from app.modules.lms.domain.authoring.errors import SettingsInvalidError

import pytest


class _Groups:
    def __init__(self, known: set[UUID]) -> None:
        self.known = known

    async def existing_group_ids(self, ids: Sequence[UUID]) -> set[UUID]:
        return {i for i in ids if i in self.known}


def _use_case(groups: _Groups) -> UpdateCourseDetails:
    def no_uow() -> Any:
        raise AssertionError("validation must run before the unit of work")

    return UpdateCourseDetails(no_uow, None, groups)  # type: ignore[arg-type]


async def test_unknown_group_is_a_settings_error() -> None:
    known = uuid4()
    use_case = _use_case(_Groups({known}))
    await use_case._require_groups([str(known)])
    with pytest.raises(SettingsInvalidError) as caught:
        await use_case._require_groups([str(known), str(uuid4())])
    assert caught.value.params["field"] == "audience_group_ids"
