"""Size and page limits of a material by the role of its uploader (doc § 3.5)."""

from app.modules.library.domain.enums import UploaderRole
from app.settings import LibrarySettings


def max_file_bytes(role: UploaderRole, settings: LibrarySettings) -> int:
    """20 MB for students; teachers, librarians and Administration get 100 MB."""
    if role is UploaderRole.STUDENT:
        return settings.material_student_max_bytes
    return settings.material_teacher_max_bytes


def max_pages(role: UploaderRole, settings: LibrarySettings) -> int | None:
    """Students may upload 60 pages; nobody else is limited."""
    if role is UploaderRole.STUDENT:
        return settings.material_student_max_pages
    return None
