"""Response model of the course creators routes."""

from uuid import UUID

from app.modules.identity.domain.user import User

from pydantic import BaseModel


class CourseCreatorResponse(BaseModel):
    """CourseCreator: a person who holds the `lms_creator` role."""

    id: UUID
    login: str | None
    first_name: str
    last_name: str
    middle_name: str | None
    status: str

    @classmethod
    def of(cls, user: User) -> "CourseCreatorResponse":
        """Map a user."""
        return cls(
            id=user.id,
            login=user.login,
            first_name=user.first_name,
            last_name=user.last_name,
            middle_name=user.middle_name,
            status=user.status.value,
        )
