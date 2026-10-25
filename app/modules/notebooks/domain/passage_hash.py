"""The identity of a passage text: the key a derived value (an embedding) hangs on."""

import hashlib


def passage_hash(text: str) -> str:
    """sha256 (hex, 64 chars) of the passage text as UTF-8.

    The same text gives the same hash in every document and notebook, so a vector
    computed for a passage once is found again for every passage with that text. The
    migration computes the same value in SQL: `encode(sha256(convert_to(text,
    'UTF8')), 'hex')`.
    """
    return hashlib.sha256(text.encode()).hexdigest()
