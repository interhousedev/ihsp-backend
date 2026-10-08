"""Cache-Control values of the learning endpoints (README → Course versioning, 5)."""

from typing import Final

# Immutable live content: browsers may reuse it for a minute, never shared caches.
PRIVATE_CACHE: Final = "private, max-age=60"
# State that changes with every action of the student.
PRIVATE_NO_STORE: Final = "private, no-store"
