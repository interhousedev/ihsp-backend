"""Web search settings (`IHSP_WEB_SEARCH__...`): how the search runs and what it skips.

The daily quotas and the result counts are in `LimitsSettings`
(`IHSP_LIMITS__WEB_SEARCH_*`), the on/off switch is `IHSP_FEATURES__WEB_SEARCH` and
the models are the AI tasks `web_search` and `discover`.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Sites a school platform never offers to a student of 14 to 18. They are sent to the
# search engine as excluded domains and checked again on every result, so that an
# engine which ignores the filter cannot bring them back. The deployment extends the
# list with `WEB_SEARCH__BLOCKED_DOMAINS`.
DEFAULT_BLOCKED_DOMAINS: tuple[str, ...] = (
    "4chan.org",
    "8kun.top",
    "kiwifarms.net",
    "onlyfans.com",
    "pornhub.com",
    "xhamster.com",
    "xnxx.com",
    "xvideos.com",
)


def _domain_list(value: object) -> object:
    """Turn `a.com, b.org` from the environment into a tuple (a JSON list works too)."""
    if isinstance(value, str):
        return tuple(
            part.strip().lower().removeprefix("www.")
            for part in value.split(",")
            if part.strip()
        )
    return value


class DbFirstSettings(BaseModel):
    """Look in the platform's database before the web (`WEB_SEARCH__DB_FIRST__...`)."""

    enabled: bool = True
    """Off: always search the web."""

    min_coverage: float = Field(default=0.7, ge=0, le=1)
    """Share of the query terms the dense passages must cover to skip the web."""

    min_passages: int = Field(default=3, ge=1, le=20)
    """Dense passages needed to skip the web."""

    min_density: float = Field(default=0.2, gt=0, le=1)
    """On-topic tokens / all tokens a passage needs to count as dense."""

    candidates: int = Field(default=12, ge=1, le=50)
    """Passages asked from the database."""


class WebSearchSettings(BaseModel):
    """How a web search call is made; see docs/reference/notebooklm.md."""

    surface: Literal["plugin", "server_tool"] = "plugin"
    """OpenRouter feature that runs the search. `plugin` is the `web` plugin: it
    searches exactly once per call, so a quota unit is one search (OpenRouter marks it
    deprecated). `server_tool` is `openrouter:web_search`: the model decides to search,
    at most once here, and `max_characters` caps the text of each result."""

    engine: Literal["exa", "parallel", "perplexity"] = "exa"
    """Search engine behind OpenRouter. Native search of a model provider is not used:
    its results come with different annotations and no result count."""

    mode: str | None = Field(default=None, min_length=1)
    """Engine mode (Exa `auto`, `fast`, ..., Parallel `basic`, `turbo`, ...). Empty:
    the engine's own default."""

    blocked_domains: tuple[str, ...] = DEFAULT_BLOCKED_DOMAINS
    """Comma list of domains never searched, shown or added as a web source; a domain
    blocks its subdomains too. Replaces the built-in list."""

    snippet_chars: int = Field(default=1200, ge=200, le=4000)
    """Longest excerpt of a result kept in a message and given to the model."""

    timeout_seconds: int = Field(default=45, ge=5, le=180)
    """Timeout of one search call (the search engine runs inside it)."""

    db_first: DbFirstSettings = Field(default_factory=DbFirstSettings)

    @field_validator("blocked_domains", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        return _domain_list(value)
