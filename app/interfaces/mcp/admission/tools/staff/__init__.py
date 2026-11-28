"""The staff family of the admission server: caseload, students, document review."""

from app.interfaces.mcp.admission.tools.staff import caseload, review, students
from app.interfaces.mcp.toolkit import ToolKit


def register_staff(kit: ToolKit) -> None:
    """Register every staff tool (each carries `roles=ADMISSION_STAFF_ROLES`)."""
    caseload.register(kit)
    students.register(kit)
    review.register(kit)
