"""Fixtures of the Level scheme HTTP tests: the learning services, actors and client."""

from tests.lms.learning.conftest import (  # noqa: F401
    deps,
    identity,
    learning,
    lms_admin,
    maker,
    other_student,
    previews,
    student,
    teacher,
)
from tests.lms.learning.http.conftest import (  # noqa: F401
    anonymous_client,
    caller,
    client,
)
