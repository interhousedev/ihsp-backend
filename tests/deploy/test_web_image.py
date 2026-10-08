"""The prebuilt web image (local stack) stays in step with the full web image."""

import re

from tests.deploy.helpers import BACKEND_DIR, SCRIPTS_DIR

WEB_DEPLOY = BACKEND_DIR.parent / "web" / "deploy"
APPS = ("id", "sp", "staff", "admin", "lms", "share")


def _nginx_stage(name: str) -> list[str]:
    """Instructions after `FROM nginx`, continuation lines joined, comments dropped."""
    text = (WEB_DEPLOY / name).read_text(encoding="utf-8")
    stage = text[text.index("FROM nginx") :]
    stage = re.sub(r"\\\n\s*", " ", stage)
    lines = [line.strip() for line in stage.splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def _is_app_copy_or_chmod(line: str) -> bool:
    return line.startswith(("COPY --from=builder", "COPY apps/")) or line.startswith(
        "RUN chmod +x /app/entrypoint.sh"
    )


def test_the_nginx_stages_of_both_dockerfiles_match() -> None:
    full = [x for x in _nginx_stage("Dockerfile") if not _is_app_copy_or_chmod(x)]
    prebuilt = [
        x for x in _nginx_stage("Dockerfile.prebuilt") if not _is_app_copy_or_chmod(x)
    ]
    assert prebuilt == full


def test_both_dockerfiles_place_every_app_in_the_same_directory() -> None:
    full = (WEB_DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    prebuilt = (WEB_DEPLOY / "Dockerfile.prebuilt").read_text(encoding="utf-8")
    for app in APPS:
        target = "/srv/share/ai" if app == "share" else f"/srv/{app}"
        assert f"COPY --from=builder /app/apps/{app}/out {target}\n" in full
        assert f"COPY apps/{app}/out {target}\n" in prebuilt


def test_the_prebuilt_context_is_an_allow_list_of_the_exports() -> None:
    lines = (WEB_DEPLOY / "Dockerfile.prebuilt.dockerignore").read_text().splitlines()
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*"
    assert set(rules[1:]) == {"!deploy", *(f"!apps/{app}/out" for app in APPS)}


def test_the_prebuilt_image_refuses_exports_without_the_csp_meta() -> None:
    text = (WEB_DEPLOY / "Dockerfile.prebuilt").read_text(encoding="utf-8")
    assert 'http-equiv="Content-Security-Policy"' in text
    assert "bun deploy/csp-hash.ts" in text


def test_local_up_builds_the_apps_one_at_a_time_on_the_host() -> None:
    script = (SCRIPTS_DIR / "local_up.sh").read_text(encoding="utf-8")
    assert "--full-build" in script
    assert 'bun run --filter "./apps/$app" build' in script
    assert "deploy/Dockerfile.prebuilt" in script
    assert "bun deploy/csp-hash.ts" in script
    # one `bun run --filter` per app, never the parallel `bun run build` of the root
    code = [x for x in script.splitlines() if not x.lstrip().startswith("#")]
    assert not any("bun run build" in line for line in code)
