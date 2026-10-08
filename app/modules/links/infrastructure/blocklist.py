"""Loading the domain blocklist (SL-8)."""

from pathlib import Path

DEFAULT_BLOCKLIST = Path(__file__).with_name("blocklist.txt")


def load_blocklist(path: Path = DEFAULT_BLOCKLIST) -> frozenset[str]:
    """Read one domain per line; blank lines and comments are skipped."""
    domains = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip().lower().rstrip(".")
        if entry and not entry.startswith("#"):
            domains.add(entry)
    return frozenset(domains)
