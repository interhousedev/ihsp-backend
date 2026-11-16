"""Chances of the student at one institution (no AI, no stored state)."""

from decimal import Decimal
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.chances import (
    Chances,
    Preferences,
    Simulation,
    StudentData,
    evaluate,
)
from app.modules.admission.domain.classification import signals_of
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.matching import PreferenceAnswers
from app.modules.admission.domain.runtime_settings import ESTIMATES_STUDENT_VISIBLE
from app.modules.admission.ports.unit_of_work import UowFactory
from app.settings_admission import AdmissionSettings

SAT_KEY = "sat"


class ChancesService:
    """Reads the student's own data and judges one institution."""

    def __init__(
        self,
        uow_factory: UowFactory,
        runtime: RuntimeSettingsService,
        settings: AdmissionSettings,
    ) -> None:
        """Keep the unit-of-work factory and the runtime switch."""
        self._uow = uow_factory
        self._runtime = runtime
        self._settings = settings

    async def for_institution(
        self, ctx: AdmissionContext, institution_id: UUID
    ) -> Chances:
        """Chances of the caller at an institution; not found if it is unknown."""
        sid = ctx.user_id
        async with self._uow() as uow:
            inst = await uow.catalog.institution(institution_id)
            if inst is None:
                raise AdmissionNotFoundError()
            profile = await uow.profiles.get(sid)
            band = await uow.shortlist.budget_band(sid)
            items = await uow.items.list_for(sid)
            courses = [c for c in await uow.courses.list_for(sid) if c.included]
            tests = {
                t.id: t for t in await uow.test_scores.catalog(include_inactive=True)
            }
            entries = await uow.test_scores.entries(sid)
            stored = await uow.preferences.get(sid)
        sat = [
            float(e.total)
            for e in entries
            if e.status == "score_received"
            and isinstance(e.total, Decimal)
            and e.test_id in tests
            and tests[e.test_id].key == SAT_KEY
        ]
        answers = stored[0] if stored else PreferenceAnswers()
        signals = signals_of(profile.answers) if profile is not None else None
        data = StudentData(
            gpa_ratio=signals.gpa_ratio if signals else None,
            sat_total=max(sat) if sat else None,
            activities=sum(1 for i in items if i.kind == "activity"),
            honors=sum(1 for i in items if i.kind == "honor"),
            course_titles=[c.title for c in courses],
            course_levels=[c.level for c in courses],
            budget_band=band,
            prefs=Preferences(
                budget=answers.budget,
                region=answers.region,
                need_aid=answers.need_aid,
            ),
        )
        result = evaluate(inst, data)
        rs = await self._runtime.get()
        if rs.get(ESTIMATES_STUDENT_VISIBLE, self._settings.estimates_student_visible):
            return result
        sim = result.simulation
        return Chances(
            None,
            "estimates_hidden",
            result.factors,
            Simulation(sim.metric, sim.your_value, None, None, ()),
        )
