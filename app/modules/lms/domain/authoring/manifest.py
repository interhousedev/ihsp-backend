"""Version manifests: the outline of a published course with revision pointers.

Stored as `{"sections": [{"id", "title", "steps": [{"step_id", "revision_id",
"title"}]}]}` (README → Course versioning). Readers also accept a bare list of
sections.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.lms.domain.authoring.outline import Outline, sections_of


@dataclass(frozen=True, slots=True)
class ManifestStep:
    """One step of a version, pinned to a revision."""

    section_id: str
    step_id: UUID
    revision_id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class ManifestSection:
    """One section of a version."""

    id: str
    title: str
    steps: tuple[ManifestStep, ...]


def parse_manifest(raw: Any) -> list[ManifestSection]:  # noqa: ANN401 - stored JSON
    """Read the stored outline of a version."""
    sections = raw if isinstance(raw, list) else (raw or {}).get("sections", [])
    return [
        ManifestSection(
            id=section["id"],
            title=section["title"],
            steps=tuple(
                ManifestStep(
                    section_id=section["id"],
                    step_id=UUID(str(entry["step_id"])),
                    revision_id=UUID(str(entry["revision_id"])),
                    title=entry.get("title", ""),
                )
                for entry in section.get("steps", [])
            ),
        )
        for section in sections
    ]


def manifest_steps(sections: Sequence[ManifestSection]) -> list[ManifestStep]:
    """Flatten sections into steps in outline order."""
    return [step for section in sections for step in section.steps]


def build_manifest(
    outline: Outline,
    revisions: Mapping[UUID, UUID],
    titles: Mapping[UUID, str],
) -> dict[str, Any]:
    """Build the stored outline of a new version from the draft outline.

    Args:
        outline: Draft outline (step IDs as strings).
        revisions: Revision pinned for each step ID.
        titles: Step title at publish time for each step ID.
    """
    return {
        "sections": [
            {
                "id": section["id"],
                "title": section["title"],
                "steps": [
                    {
                        "step_id": step,
                        "revision_id": str(revisions[UUID(step)]),
                        "title": titles[UUID(step)],
                    }
                    for step in section["steps"]
                ],
            }
            for section in sections_of(outline)
        ]
    }


def outline_from_manifest(sections: Sequence[ManifestSection]) -> Outline:
    """Turn a version's outline back into a draft outline."""
    return {
        "sections": [
            {
                "id": section.id,
                "title": section.title,
                "steps": [str(step.step_id) for step in section.steps],
            }
            for section in sections
        ]
    }
