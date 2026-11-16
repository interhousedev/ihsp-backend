"""Deterministic fake document for the admission task suggestions."""

from typing import Any

TASKS_SCHEMA = "tasks_suggest"


def build_tasks_document(schema_name: str) -> dict[str, Any] | None:
    """Return a schema-valid tasks document, else None."""
    if schema_name != TASKS_SCHEMA:
        return None
    return {
        "tasks": [
            {
                "title": "Outline your personal statement",
                "description": "Pick one story and write a one-page outline.",
                "priority": "high",
                "deadline": "",
                "steps": [
                    {
                        "title": "List three possible stories",
                        "link_label": "",
                        "link_url": "",
                        "link_kind": "external",
                    },
                    {
                        "title": "Draft the outline",
                        "link_label": "Essays",
                        "link_url": "/essays/",
                        "link_kind": "internal",
                    },
                ],
                "links": [],
            },
            {
                "title": "Check the requirements of your target universities",
                "description": "Note tests, documents and deadlines of each one.",
                "priority": "medium",
                "deadline": "",
                "steps": [],
                "links": [],
            },
        ]
    }
