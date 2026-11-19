"""Fakes for the opportunity relevance tests."""

from typing import Any
from uuid import UUID

from app.modules.admission.domain.opportunities import Opportunity, OpportunityDraft
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW
from tests.admission.unit.test_opportunities import Env, _draft


class RelevanceEnv(Env):
    """The opportunity service over fakes with a helper to publish entries."""

    def publish(self, title: str, *fields: str, **kw: Any) -> UUID:
        """Add a published entry with the given canonical study fields."""
        draft: OpportunityDraft = _draft(
            new_id(), title=title, study_field_ids=tuple(fields), **kw
        )
        oid = new_id()
        self.repo.rows[oid] = Opportunity(
            id=oid,
            draft=draft,
            created_by=new_id(),
            created_at=NOW,
            updated_at=NOW,
            archived=False,
            lock_version=1,
        )
        return oid
