"""McpLearningRecordTools over the lms and certificates modules.

Owner-scoped reads; the use cases enforce the anti-cheating rule (D2): an attempt
carries question texts only when the step's answers policy shows them to the
student. AI-review results are the final verdict only, never the chat or files.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.bootstrap.adapters.admission_certificates import AdmissionCertificatesAdapter
from app.interfaces.mcp.constants import ERROR_LOCALE
from app.modules.certificates.domain.course.values import IssuedCertificate
from app.modules.certificates.domain.errors import CourseCertificateNotFoundError
from app.modules.lms.application.learning.ai_review import AiReviews, parse_verdict
from app.modules.lms.domain.learning.ai_review_errors import (
    AiReviewSessionNotFoundError,
)
from app.shared.actor import Actor
from app.shared.contracts.mcp_learning_record import McpLearningRecordTools

if TYPE_CHECKING:
    from app.bootstrap.container import Container


def _label(labels: dict[str, str], fallback: str) -> str:
    return labels.get(ERROR_LOCALE) or labels.get("en") or fallback


class McpLearningAdapter:
    """The caller's own learning record; a foreign id is not found."""

    def __init__(self, container: "Container") -> None:
        """Keep the container; modules are read lazily."""
        self.container = container

    def _reviews(self) -> AiReviews | None:
        return self.container.lms.learning.ai_review

    def _certificate(self, cert: IssuedCertificate | None) -> dict[str, Any] | None:
        if cert is None or cert.revoked_at is not None:
            return None
        return {
            "tier": _label(cert.tier_label, cert.tier_key),
            "issued_at": cert.issued_at,
            "verify_url": self.container.course_certificates.verify_url(cert.code),
        }

    async def courses(self, actor: Actor) -> list[dict[str, Any]]:
        """Enrolled courses with progress, the certificate status and badges."""
        rows = await self.container.lms.learning.learning_record.courses(actor)
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                status = await self.container.course_certificates.mine(
                    actor.user_id, row.course_id
                )
            except CourseCertificateNotFoundError:
                status = None
            out.append(
                {
                    "course_id": row.course_id,
                    "title": row.title,
                    "progress_pct": row.progress_pct,
                    "score_pct": status.score_pct if status else None,
                    "passing_pct": (
                        status.passing_pct if status and status.enabled else None
                    ),
                    "required_steps_left": (
                        status.required_steps_left if status else None
                    ),
                    "certificate": self._certificate(
                        status.certificate if status else None
                    ),
                    "badges_earned": row.badges_earned,
                    "last_activity_at": row.last_activity_at,
                }
            )
        return out

    async def course_progress(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """The mastery map of an enrolled course."""
        view = await self.container.lms.learning.learning_record.course_progress(
            actor, course_id
        )
        return view.model_dump()

    async def my_attempts(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        step_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        """Submitted attempts of an enrolled course, newest first."""
        page = await self.container.lms.learning.learning_record.my_attempts(
            actor, course_id, step_id=step_id, limit=limit, cursor=cursor
        )
        return page.model_dump()

    async def my_attempt(self, actor: Actor, attempt_id: UUID) -> dict[str, Any]:
        """One submitted attempt under the answers policy."""
        view = await self.container.lms.learning.learning_record.my_attempt(
            actor, attempt_id
        )
        return view.model_dump()

    async def my_ai_reviews(
        self, actor: Actor, *, course_id: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        """The caller's AI-review sessions with a submission."""
        reviews = self._reviews()
        if reviews is None:
            return []
        sessions = await reviews.list_my_sessions(actor, course_id, limit)
        return [s.model_dump() for s in sessions]

    async def my_ai_review(self, actor: Actor, session_id: UUID) -> dict[str, Any]:
        """The verdict of the caller's session."""
        reviews = self._reviews()
        if reviews is None:
            raise AiReviewSessionNotFoundError(params={"session_id": str(session_id)})
        return (await reviews.verdict_of(actor, session_id)).model_dump()

    async def my_certificates(self, actor: Actor) -> dict[str, Any]:
        """Issued course certificates and the school certificate entries."""
        course: list[dict[str, Any]] = []
        for row in await self.container.lms.learning.learning_record.courses(actor):
            cert = await self._held(actor.user_id, row.course_id)
            if cert is not None:
                course.append({"course_id": row.course_id, "title": row.title, **cert})
        certificates = self.container.certificates
        school = await AdmissionCertificatesAdapter(
            certificates.list_types, certificates.list_my_entries
        ).for_student(actor.user_id)
        return {
            "course": course,
            "school": [
                {
                    "id": entry.entry_id,
                    "type": entry.type_code,
                    "title": entry.name(ERROR_LOCALE),
                    "date": entry.issued_at,
                }
                for entry in school
            ],
        }

    async def _held(self, user_id: UUID, course_id: UUID) -> dict[str, Any] | None:
        try:
            status = await self.container.course_certificates.mine(user_id, course_id)
        except CourseCertificateNotFoundError:
            return None
        return self._certificate(status.certificate)

    async def my_badges(self, actor: Actor) -> dict[str, Any]:
        """Earned and locked badges across the enrolled courses."""
        view = await self.container.lms.badges.mine(actor)
        return {
            "earned": [
                {
                    "badge_id": e.badge.id,
                    "course_id": e.course_id,
                    "course_title": e.course_title,
                    "title": _label(e.badge.name.model_dump(), ""),
                    "awarded_at": e.awarded_at,
                }
                for e in view.earned
            ],
            "locked": [
                {
                    "badge_id": b.badge.id,
                    "course_id": b.course_id,
                    "course_title": b.course_title,
                    "title": _label(b.badge.name.model_dump(), ""),
                    "hint": str(b.hint),
                }
                for b in view.locked
            ],
        }

    async def ai_review_submissions(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        block_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Staff: sessions of a block with a submission and their verdicts."""
        reviews = self._reviews()
        if reviews is None:
            return []
        rows = await reviews.list_submissions(actor, course_id, step_id, block_id)
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            verdict = parse_verdict(row.review_openui)
            out.append(
                {
                    "session_id": row.session_id,
                    "student": {"id": row.student.id, "name": row.student.name},
                    "status": row.status,
                    "submitted_at": row.submitted_at,
                    "reviewed": row.review_openui is not None,
                    **verdict,
                }
            )
        return out


def build_learning_tools(container: "Container") -> McpLearningRecordTools:
    """Build the backend of the learning-record tools."""
    return McpLearningAdapter(container)
