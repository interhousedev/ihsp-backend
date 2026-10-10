"""Wiring entry point of the composition endpoints (used by bootstrap, task I1).

```python
composition = composition_from_container(container, ports)
install_composition(app, composition)
```

`ports` is a `CompositionPorts` whose members I1 implements over the provider modules
(see `ports.py`). The cross-module contracts are read from the container.
"""

from app.bootstrap.container import Container
from app.interfaces.http.v1.composition.application.build_admin_dashboard import (
    BuildAdminDashboard,
)
from app.interfaces.http.v1.composition.application.build_alerts import BuildAlerts
from app.interfaces.http.v1.composition.application.build_calendar_feed import (
    BuildCalendarFeed,
)
from app.interfaces.http.v1.composition.application.build_group_stats import (
    BuildGroupStats,
)
from app.interfaces.http.v1.composition.application.build_student_360 import (
    BuildStudent360,
)
from app.interfaces.http.v1.composition.application.build_teacher_profile import (
    BuildTeacherProfile,
)
from app.interfaces.http.v1.composition.application.issue_calendar_token import (
    IssueCalendarToken,
)
from app.interfaces.http.v1.composition.application.search_all import SearchAll
from app.interfaces.http.v1.composition.ports import CompositionPorts
from app.interfaces.http.v1.composition.services import Composition
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory

from fastapi import FastAPI


def build_composition(
    *,
    settings: Settings,
    clock: Clock,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    classwork: ClassworkQueries,
    marks: MarksQueries,
    ai: AiQueries,
    flashcards: FlashcardsApi,
    ports: CompositionPorts,
) -> Composition:
    """Connect the composition use cases to contracts and local ports."""
    return Composition(
        build_alerts=BuildAlerts(
            identity=identity,
            schedule=schedule,
            ai=ai,
            files=ports.files,
            sync=ports.sync,
            clock=clock,
            urls=settings.urls,
        ),
        search_all=SearchAll(
            identity=identity,
            schedule=schedule,
            classwork=classwork,
            marks=marks,
            files=ports.files,
            flashcards=flashcards,
            sources=ports.search_sources,
            clock=clock,
        ),
        issue_calendar_token=IssueCalendarToken(
            tokens=ports.calendar_tokens, api_url=settings.urls.api
        ),
        build_calendar_feed=BuildCalendarFeed(
            tokens=ports.calendar_tokens,
            overview=ports.schedule_overview,
            schedule=schedule,
            identity=identity,
            clock=clock,
            calendar_name=settings.public_app_name,
        ),
        build_admin_dashboard=BuildAdminDashboard(
            identity=identity,
            classwork=classwork,
            overview=ports.schedule_overview,
            sync=ports.sync,
            broadcasts=ports.broadcasts,
            clock=clock,
        ),
        build_group_stats=BuildGroupStats(
            overview=ports.schedule_overview,
            attendance=ports.attendance_stats,
            schedule=schedule,
            marks=marks,
            clock=clock,
        ),
        build_student_360=BuildStudent360(
            identity=identity,
            schedule=schedule,
            students=ports.students,
            accounts=ports.accounts,
            clock=clock,
        ),
        build_teacher_profile=BuildTeacherProfile(
            identity=identity,
            teachers=ports.teachers,
            accounts=ports.accounts,
            clock=clock,
        ),
    )


def composition_from_container(
    container: Container, ports: CompositionPorts
) -> Composition:
    """Build the composition from the module services of the container."""
    return build_composition(
        settings=container.settings,
        clock=container.clock,
        identity=container.identity.directory,
        schedule=container.academic.schedule.queries,
        classwork=container.academic.classwork.queries,
        marks=container.academic.marks.queries,
        ai=container.ai.public,
        flashcards=container.flashcards.public,
        ports=ports,
    )


def install_composition(app: FastAPI, composition: Composition) -> None:
    """Make the composition available to the handlers of `app`."""
    app.state.composition = composition
