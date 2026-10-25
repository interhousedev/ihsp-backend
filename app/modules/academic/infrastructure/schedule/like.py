"""LIKE patterns with escaped wildcards."""

ESCAPE = "\\"


def like_pattern(query: str) -> str:
    """Return a contains-pattern with LIKE wildcards escaped."""
    escaped = (
        query.replace(ESCAPE, ESCAPE * 2)
        .replace("%", ESCAPE + "%")
        .replace("_", ESCAPE + "_")
    )
    return f"%{escaped}%"
