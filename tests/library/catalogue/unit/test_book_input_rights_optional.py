"""The book form needs no rights field: it defaults to `official`."""

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import BookInputBody
from app.modules.library.domain.enums import Rights


def test_rights_is_optional_in_the_book_form() -> None:
    assert BookInputBody.model_fields["rights"].is_required() is False
    assert BookInputBody.model_fields["rights"].default is Rights.OFFICIAL
