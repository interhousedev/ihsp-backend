"""EMIS rating book response (``POST student-profiles/rating-book/``)."""

from pydantic import BaseModel


class RatingBookV1DTO(BaseModel):
    """The ``result`` object: the address of the generated PDF."""

    url: str
