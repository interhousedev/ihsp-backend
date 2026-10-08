"""Enumerations of the course authoring domain."""

from enum import StrEnum


class Visibility(StrEnum):
    """Who may enroll in a course (LMS-3)."""

    PUBLIC = "public"
    INVITE = "invite"


class CourseStatus(StrEnum):
    """Lifecycle of a course."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class StepVia(StrEnum):
    """Where a draft change came from (the "via MCP" badge)."""

    UI = "ui"
    MCP = "mcp"


class RevisionKind(StrEnum):
    """How a step revision was created."""

    PUBLISH = "publish"
    CHECKPOINT = "checkpoint"
    PREVIEW = "preview"


class StepChange(StrEnum):
    """What happened to a step between two states of a course."""

    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"
    SAME = "same"
