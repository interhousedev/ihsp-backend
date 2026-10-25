"""Request and response models of the teacher routes."""

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse

from pydantic import BaseModel, EmailStr, Field


class TeacherCreateBody(BaseModel):
    """POST /v1/admin/teachers."""

    last_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=255)
    middle_name: str | None = Field(default=None, max_length=255)
    email: EmailStr


class TeacherPatchBody(BaseModel):
    """PATCH /v1/admin/teachers/{id}."""

    last_name: str | None = Field(default=None, min_length=1, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    middle_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None


class TeacherCreatedResponse(BaseModel):
    """The new account and its activation link."""

    user: AdminUserResponse
    activation_url: str
