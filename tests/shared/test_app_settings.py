"""PWA-3: the installed app's version settings and the app origin."""

from app.settings import AppSettings, Settings

import pytest
from pydantic import ValidationError


def test_the_app_versions_default_to_1_0_0() -> None:
    """PWA-3: a fresh install reports 1.0.0 for both numbers."""
    settings = Settings()

    assert settings.app.latest == "1.0.0"
    assert settings.app.min_supported == "1.0.0"


def test_the_app_origin_defaults_to_the_second_next_dev_port() -> None:
    """PWA-1: sp runs on 3002, the PWA build of the same app on 3007."""
    assert Settings().urls.app == "http://localhost:3007"


def test_the_app_origin_is_allowed_by_cors() -> None:
    """PWA-1: the cookie endpoints accept Origin app.<domain>."""
    settings = Settings(urls={"app": "https://app.ihsu.uz/"})

    assert "https://app.ihsu.uz" in settings.cors_app_origins()


def test_environment_sets_the_versions_and_the_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PWA-3: IHSP_APP__LATEST, IHSP_APP__MIN_SUPPORTED and IHSP_URLS__APP."""
    monkeypatch.setenv("IHSP_APP__LATEST", "1.10.0")
    monkeypatch.setenv("IHSP_APP__MIN_SUPPORTED", "1.9")
    monkeypatch.setenv("IHSP_URLS__APP", "https://app.ihsu.uz")

    settings = Settings()

    assert settings.app.latest == "1.10.0"
    assert settings.app.min_supported == "1.9"
    assert settings.urls.app == "https://app.ihsu.uz"


@pytest.mark.parametrize("bad", ["abc", "", "1.", "1.x", "-1", "1.0-beta", "v1"])
def test_a_version_that_is_not_dotted_integers_is_rejected(bad: str) -> None:
    """PWA-3: the settings refuse to start with a malformed version."""
    with pytest.raises(ValidationError, match="version"):
        AppSettings(latest=bad)
    with pytest.raises(ValidationError, match="version"):
        AppSettings(latest="9.0.0", min_supported=bad)


def test_a_bad_version_in_the_environment_stops_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PWA-3: IHSP_APP__LATEST=abc fails at startup, not at the first request."""
    monkeypatch.setenv("IHSP_APP__LATEST", "abc")

    with pytest.raises(ValidationError, match="version"):
        Settings()


def test_min_supported_above_latest_is_rejected() -> None:
    """PWA-3: nobody can be forced onto a version that does not exist yet."""
    with pytest.raises(ValidationError, match="min_supported"):
        AppSettings(latest="1.2.0", min_supported="1.3.0")


def test_versions_are_compared_numerically_not_as_text() -> None:
    """PWA-3: "1.10.0" is above "1.9.0", though the text sorts below."""
    ok = AppSettings(latest="1.10.0", min_supported="1.9.0")

    assert (ok.latest, ok.min_supported) == ("1.10.0", "1.9.0")
    with pytest.raises(ValidationError, match="min_supported"):
        AppSettings(latest="1.9.0", min_supported="1.10.0")


def test_missing_segments_count_as_zero_when_comparing() -> None:
    """PWA-3: latest "1.4" with min_supported "1.4.0" is the same version."""
    settings = AppSettings(latest="1.4", min_supported="1.4.0")

    assert settings.latest == "1.4"
    with pytest.raises(ValidationError, match="min_supported"):
        AppSettings(latest="1.4", min_supported="1.4.1")


def test_min_supported_may_equal_or_trail_latest() -> None:
    """PWA-3: equal is fine (everyone must update), and lower is the usual case."""
    AppSettings(latest="2.0.0", min_supported="2.0.0")
    AppSettings(latest="2.0.0", min_supported="1")
