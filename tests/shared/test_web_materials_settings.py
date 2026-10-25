"""Web materials: defaults of the switch, the caps, the limits and the AI tasks."""

from app.settings import Settings
from app.shared.ai_tasks import CHEAP_MODEL, MEDIA_MODEL, AiTask
from app.shared.limits import UNLIMITED, ActorLimits, is_unlimitable


def test_defaults() -> None:
    """On by default with ten candidates of at most 20 MB a page."""
    cfg = Settings().notebooks
    assert cfg.web_materials_enabled is True
    assert cfg.web_materials_per_page == 10
    assert cfg.web_materials_max_bytes == 20 * 1024 * 1024
    assert cfg.web_materials_min_image_px == 200


def test_daily_limits_are_editable_and_may_be_unlimited() -> None:
    """Both counters are quotas that accept -1 (read as no cap)."""
    limits = Settings().limits
    assert (limits.nb_web_materials_per_day, limits.nb_media_described_per_day) == (
        30,
        20,
    )
    for name in ("nb_web_materials_per_day", "nb_media_described_per_day"):
        assert is_unlimitable(name)
    lifted = limits.model_copy(update={"nb_web_materials_per_day": UNLIMITED})
    assert ActorLimits(lifted, unlimited=False).nb_web_materials_per_day is None


def test_the_tasks_run_on_cheap_private_models() -> None:
    """Triage on the cheap model, media on the vision and audio model, no training."""
    settings = Settings()
    triage = settings.ai_profile(AiTask.WEB_MATERIAL_TRIAGE)
    media = settings.ai_profile(AiTask.MEDIA_DESCRIBE)
    assert (triage.model, media.model) == (CHEAP_MODEL, MEDIA_MODEL)
    assert triage.data_collection == media.data_collection == "deny"
    assert {"image", "audio"} <= set(media.modalities)
