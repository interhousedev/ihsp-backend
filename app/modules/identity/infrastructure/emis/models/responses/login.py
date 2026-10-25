"""EMIS login response."""

from pydantic import BaseModel


class LoginResultV1DTO(BaseModel):
    """The ``result`` object of ``POST student-profiles/login/``."""

    access_token: str
