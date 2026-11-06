"""Our own links in tool results (A4), built from settings and templates only.

Addresses found in content never come here; they go to `external_url` through
`untrusted.safe_external_url`. The web apps are static exports: paths end with a slash
and entities are addressed by query parameter, except the LMS course player.
"""

from urllib.parse import urlencode
from uuid import UUID

from app.settings import Settings

Links = dict[str, str]


class McpLinks:
    """Typed link builders; each returns a dict with at least `open`."""

    def __init__(self, settings: Settings) -> None:
        """Keep the public origins."""
        self._urls = settings.urls

    def flashcard_set(self, set_id: UUID) -> Links:
        """A flash card set and its study session."""
        return {
            "open": self._sp("flashcards/set", id=set_id),
            "study": self._sp("flashcards/study", id=set_id),
        }

    def notebook(self, notebook_id: UUID) -> Links:
        """A notebook workspace."""
        return {"open": self._sp("notebooks/view", id=notebook_id)}

    def quiz(self, notebook_id: UUID, artifact_id: UUID) -> Links:
        """A quiz artifact opened in its notebook workspace."""
        return {
            "open": self._sp("notebooks/view", id=notebook_id, artifact=artifact_id)
        }

    def lesson(self, lesson_id: UUID) -> Links:
        """A lesson of the student app."""
        return {"open": self._sp("lessons/view", id=lesson_id)}

    def teacher(self, teacher_id: UUID) -> Links:
        """A teacher's page of the student app."""
        return {"open": self._sp("teachers/view", id=teacher_id)}

    def files(self) -> Links:
        """The files page; the web app has no link to one file yet."""
        return {"open": self._sp("files")}

    def course_step(self, course_id: UUID, step_id: UUID) -> Links:
        """A step in the course player."""
        base = self._urls.lms.rstrip("/")
        return {"open": f"{base}/course/{course_id}/step/{step_id}/"}

    def library_item(self, item_id: UUID) -> Links:
        """A library item."""
        base = self._urls.library.rstrip("/")
        return {"open": f"{base}/item/?{urlencode({'id': str(item_id)})}"}

    def connectors(self) -> Links:
        """The page where the user changes what a connector may do."""
        return {"open": f"{self._urls.id.rstrip('/')}/connectors/"}

    def settings(self) -> Links:
        """The student app's settings, where the EMIS login is renewed."""
        return {"open": self._sp("settings")}

    def _sp(self, path: str, **params: UUID) -> str:
        url = f"{self._urls.sp.rstrip('/')}/{path}/"
        if params:
            url += "?" + urlencode({key: str(value) for key, value in params.items()})
        return url
