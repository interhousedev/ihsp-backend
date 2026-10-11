"""Web search settings (`IHSP_WEB_SEARCH__...`): what the search skips and shows.

The search engine is Exa (`IHSP_EXA__...`, in `ExaSettings`). The daily quotas and the
result counts are in `LimitsSettings` (`IHSP_LIMITS__WEB_SEARCH_*`), the on/off switch
is `IHSP_FEATURES__WEB_SEARCH`, and the Discover plan and ranking use the AI task
`discover`.
"""

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
    """What a web search keeps and shows; the engine itself is `ExaSettings`."""

    blocked_domains: tuple[str, ...] = DEFAULT_BLOCKED_DOMAINS
    """Comma list of domains never searched, shown or added as a web source; a domain
    blocks its subdomains too. Replaces the built-in list."""

    snippet_chars: int = Field(default=1200, ge=200, le=4000)
    """Longest excerpt of a result kept in a message and given to the model."""

    db_first: DbFirstSettings = Field(default_factory=DbFirstSettings)

    @field_validator("blocked_domains", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        return _domain_list(value)
