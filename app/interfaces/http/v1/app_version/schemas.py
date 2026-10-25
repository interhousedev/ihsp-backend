"""Response model of the app version route."""

from pydantic import BaseModel


class AppVersionResponse(BaseModel):
    """The newest release and the oldest one that may still run (dotted integers)."""

    latest: str
    min_supported: str
