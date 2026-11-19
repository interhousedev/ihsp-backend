"""The essay columns stored only as ciphertext (`EssayCipher`), and how they are bound.

Every listed column is ``bytea`` holding a blob of
`app.modules.admission.infrastructure.essay_crypto`. The associated data of a blob is
``owner_id|record_id|column``:

- owner_id: the student who owns the essay (``essays.student_id``; a version uses the
  parent essay's student, an idea its own ``student_id``; reviews, invites and
  feedback use the student of their essay);
- record_id: the ``id`` of the row the blob is stored in;
- column: the column name as listed here.

NULL means "no value" and is never sealed; an empty string is sealed like any text.
Every write reseals the whole value. JSON columns (`SEALED_JSON`) hold the sealed
compact JSON of the value.

Stays plaintext on purpose: ``essays.prompt_text`` (the college's prompt, public),
``essays.links``, ``essay_versions.word_count``, the counters and statuses, the old
``reviews`` payloads and the generic ``comments`` table (one table for profile, item,
list entry, essay, words and help request comments; not essay text).
"""

import json
from typing import Any, Final

SEALED_COLUMNS: Final[dict[str, frozenset[str]]] = {
    "essays": frozenset({"title", "body", "notes", "plan"}),
    "essay_versions": frozenset({"body", "name"}),
    "essay_ideas": frozenset({"body", "tags"}),
    "essay_reviews": frozenset({"result"}),
    "essay_invites": frozenset({"label"}),
    "essay_feedback": frozenset({"quote", "body", "author_name"}),
}
"""Table (in the admission schema) to its sealed columns."""

SEALED_JSON: Final[frozenset[tuple[str, str]]] = frozenset(
    {("essays", "plan"), ("essay_ideas", "tags"), ("essay_reviews", "result")}
)
"""Sealed columns whose plaintext is JSON."""


def to_json(value: Any) -> str:
    """The compact JSON text that is sealed for a JSON column."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
