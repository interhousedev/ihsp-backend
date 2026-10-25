"""Shared type aliases of the learning use cases."""

from collections.abc import Callable

from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork

# A new unit of work per call: use cases are shared by concurrent requests.
UowFactory = Callable[[], LearningUnitOfWork]
