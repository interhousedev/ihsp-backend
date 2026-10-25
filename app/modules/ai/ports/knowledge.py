"""Ports: the school knowledge base and the report of unanswered questions."""

from app.shared.contracts.school_knowledge import (
    KnowledgeEntry,
    KnowledgeGapReporter,
    KnowledgeLookup,
)

__all__ = ["KnowledgeEntry", "KnowledgeGapReporter", "KnowledgeLookup"]
