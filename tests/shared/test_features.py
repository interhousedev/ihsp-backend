"""Feature flags: one variable switches a part of the product everywhere."""

from app.interfaces.http.routing import API_PACKAGES, FEATURE_PACKAGES, routers_for
from app.interfaces.jobs.schedule import (
    CRON_JOBS,
    JOB_FEATURES,
    CronScheduleSource,
    enabled_jobs,
)
from app.settings import Settings
from app.settings_features import FeaturesSettings
from app.shared.features import Feature, is_enabled

import pytest


def route_paths(settings: Settings | None) -> set[str]:
    """Every path the api process serves."""
    return {
        route.path  # type: ignore[attr-defined]
        for router in routers_for("api", settings)
        for route in router.routes
    }


def test_every_feature_has_a_flag_and_every_flag_a_feature() -> None:
    """`Feature` and `FeaturesSettings` list the same names."""
    assert {feature.value for feature in Feature} == set(FeaturesSettings.model_fields)


def test_every_feature_is_on_by_default() -> None:
    """Nothing is switched off until someone says so."""
    settings = Settings()

    assert all(is_enabled(settings, feature) for feature in Feature)


@pytest.mark.parametrize("feature", list(Feature))
def test_the_environment_switches_one_feature(
    feature: Feature, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IHSP_FEATURES__<NAME>=false turns exactly that feature off."""
    monkeypatch.setenv(f"IHSP_FEATURES__{feature.name}", "false")

    settings = Settings()

    assert not is_enabled(settings, feature)
    assert [f for f in Feature if not is_enabled(settings, f)] == [feature]


def test_the_older_notebooks_switch_still_turns_notebooks_off() -> None:
    """NOTEBOOKS__ENABLED=false keeps working next to FEATURES__NOTEBOOKS."""
    settings = Settings(notebooks={"enabled": False})  # type: ignore[arg-type]

    assert not is_enabled(settings, Feature.NOTEBOOKS)
    assert is_enabled(settings, Feature.AI_ASSISTANT)


def test_a_switched_off_feature_loses_its_routes() -> None:
    """The routers of the feature are not mounted: its URLs answer 404."""
    on = route_paths(Settings())
    switched_off = {"notebooks": False, "ai_assistant": False}
    off = route_paths(Settings(features=switched_off))  # type: ignore[arg-type]

    assert any(path.startswith("/v1/notebooks") for path in on)
    assert any(path.startswith("/v1/ai/chats") for path in on)
    assert not any(path.startswith("/v1/notebooks") for path in off)
    assert not any(path.startswith("/v1/ai/chats") for path in off)
    assert not any(path.startswith("/v1/ai/usage") for path in off)
    assert any(path.startswith("/v1/me/flashcard-sets") for path in off)


def test_without_settings_every_router_is_collected() -> None:
    """Tools that list the routes (OpenAPI export) pass no settings."""
    assert route_paths(None) == route_paths(Settings())


def test_only_router_packages_of_the_api_are_gated() -> None:
    """A gated package that is not served would be dead configuration."""
    assert set(FEATURE_PACKAGES) <= set(API_PACKAGES)


def test_a_switched_off_feature_loses_its_cron_jobs() -> None:
    """notebooks.*, mail.*, lms.*, ai.* and the EMIS sync follow their flag."""
    settings = Settings(
        features={  # type: ignore[arg-type]
            "notebooks": False,
            "mail": False,
            "emis_sync": False,
        }
    )

    names = {job.task_name for job in enabled_jobs(settings)}

    assert not any(name.startswith(("notebooks.", "mail.")) for name in names)
    assert "academic.sync_all" not in names
    assert "lms.prune_revisions" in names
    assert "ai.purge_admin_chats" in names
    assert "notify.dispatch_due" in names


def test_all_jobs_run_when_everything_is_on() -> None:
    """The default schedule is the whole schedule."""
    assert enabled_jobs(Settings()) == CRON_JOBS


async def test_the_schedule_source_serves_the_enabled_jobs() -> None:
    """The scheduler process only sends the jobs of the features that are on."""
    settings = Settings(features={"lms": False})  # type: ignore[arg-type]

    tasks = await CronScheduleSource(settings=settings).get_schedules()

    assert "lms.prune_revisions" not in {task.task_name for task in tasks}
    assert len(tasks) == len(enabled_jobs(settings))


def test_the_gated_job_prefixes_are_tasks_of_the_schedule() -> None:
    """A prefix that matches no job would be dead configuration."""
    for prefix, _ in JOB_FEATURES:
        assert any(job.task_name.startswith(prefix) for job in CRON_JOBS), prefix
