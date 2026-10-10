"""Feature flags section of the settings (`IHSP_FEATURES__<NAME>`)."""

from pydantic import BaseModel


class FeaturesSettings(BaseModel):
    """Switches for whole parts of the product; every feature is on by default.

    The one exception is `change_password_on_login`, an opt-in behaviour that is off.

    A feature that is off loses its HTTP routes (they answer 404) and its scheduled
    jobs. Read them with `app.shared.features.is_enabled`.
    """

    notebooks: bool = True
    """Notebooks (NotebookLM-style): routes and cron jobs; NOTEBOOKS__ENABLED too."""

    ai_assistant: bool = True
    """Student and Administration assistants: `/v1/ai` routes and the chat purge job."""

    flashcards: bool = True
    """Flash card sets and the spaced-repetition routes."""

    lms: bool = True
    """LMS authoring and learning routes and the revision pruning job."""

    mail: bool = True
    """Student mailboxes: the mail cron jobs (purge, bounce check, sweep)."""

    push: bool = True
    """Web Push routes. Delivery also needs PUSH__ENABLED and the VAPID keys."""

    emis_sync: bool = True
    """EMIS synchronization: the scheduled syncs and the `/v1/admin/sync` routes."""

    library: bool = True
    """The library (`library.ihsu.uz`): its HTTP routes and cron jobs. UniLibrary has
    its own switch, LIBRARY__UNILIBRARY_ENABLED."""

    web_search: bool = True
    """Web search: the toggle in the assistant and notebook chats and Discover. Off: a
    request that asks for it answers `web-search/disabled`, and the status says so."""

    vector_search: bool = True
    """Search by meaning: passage embeddings (jobs `notebooks.embed_passages`) and the
    hybrid retrieval of the notebook chat. Off: retrieval is lexical only, nothing is
    embedded and no embedding request is made. Needs the pgvector database image."""

    change_password_on_login: bool = False
    """Opt-in (default off): a user whose password an administrator set must choose a
    new one right after signing in; the id app shows a change-password step."""
