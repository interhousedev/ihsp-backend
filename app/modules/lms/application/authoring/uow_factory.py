"""Shared type aliases of the authoring use cases."""

from collections.abc import Callable

from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork

# A new unit of work per call: use cases are shared by concurrent requests.
UowFactory = Callable[[], AuthoringUnitOfWork]
