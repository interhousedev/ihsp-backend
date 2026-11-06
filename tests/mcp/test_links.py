"""A4: links built only from settings and verified web routes."""

from urllib.parse import urlsplit
from uuid import UUID

from app.interfaces.mcp.links import McpLinks
from app.settings import Settings

ID = UUID(int=5)
OTHER = UUID(int=6)


def test_student_app_links_use_the_routes_of_the_web_app(settings: Settings) -> None:
    """A4: static export, trailing slash, query parameters."""
    links = McpLinks(settings)
    sp = settings.urls.sp

    assert links.flashcard_set(ID) == {
        "open": f"{sp}/flashcards/set/?id={ID}",
        "study": f"{sp}/flashcards/study/?id={ID}",
    }
    assert links.notebook(ID) == {"open": f"{sp}/notebooks/view/?id={ID}"}
    assert links.quiz(ID, OTHER) == {
        "open": f"{sp}/notebooks/view/?id={ID}&artifact={OTHER}"
    }
    assert links.lesson(ID) == {"open": f"{sp}/lessons/view/?id={ID}"}
    assert links.files() == {"open": f"{sp}/files/"}
    assert links.teacher(ID) == {"open": f"{sp}/teachers/view/?id={ID}"}


def test_course_links_use_the_course_id_path(settings: Settings) -> None:
    """A4: `/course/<id>/step/<step>/` of the LMS app."""
    links = McpLinks(settings)
    lms = settings.urls.lms

    assert links.course_step(ID, OTHER) == {
        "open": f"{lms}/course/{ID}/step/{OTHER}/",
    }


def test_library_link_addresses_the_item(settings: Settings) -> None:
    """A4: `/item/?id=` of the library app."""
    links = McpLinks(settings).library_item(ID)

    assert links == {"open": f"{settings.urls.library}/item/?id={ID}"}


def test_connector_settings_link(settings: Settings) -> None:
    """A7: where the user changes what a connector may do."""
    assert McpLinks(settings).connectors() == {
        "open": f"{settings.urls.id}/connectors/"
    }


def test_trailing_slash_of_an_origin_does_not_double(settings: Settings) -> None:
    """A4: settings may end with a slash."""
    urls = settings.urls.model_copy(update={"sp": "https://my.example/"})
    links = McpLinks(settings.model_copy(update={"urls": urls}))

    assert urlsplit(links.notebook(ID)["open"]).path == "/notebooks/view/"
