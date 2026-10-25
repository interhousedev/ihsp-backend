"""The backend image: lean runtime stage, unprivileged user, allow-listed context."""

import re

from tests.deploy.helpers import BACKEND_DIR

DOCKERFILE = BACKEND_DIR / "Dockerfile"
DOCKERIGNORE = BACKEND_DIR / ".dockerignore"


def _runtime_stage() -> str:
    text = DOCKERFILE.read_text(encoding="utf-8")
    return text[text.index("AS runtime") :]


def _instructions(text: str) -> list[str]:
    """Instruction lines with continuations joined; comments dropped."""
    joined = re.sub(r"\\\n\s*", " ", text)
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _dockerignore_rules() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_runtime_stage_copies_the_venv_and_the_source_only() -> None:
    copies = [
        line for line in _instructions(_runtime_stage()) if line.startswith("COPY ")
    ]
    assert copies == [
        "COPY --from=builder /app/.venv /app/.venv",
        "COPY app ./app",
        "COPY locales ./locales",
        "COPY migrations ./migrations",
        "COPY alembic.ini ./alembic.ini",
    ]


def test_the_runtime_stage_adds_only_libmagic_and_no_installer_or_compiler() -> None:
    runtime = _instructions(_runtime_stage())
    packages = re.findall(
        r"apt-get install -y --no-install-recommends (\S+)", " ".join(runtime)
    )
    assert packages == ["libmagic1"]
    assert not any("uv " in line or "gcc" in line for line in runtime)


def test_the_builder_installs_the_locked_dependencies_without_the_project() -> None:
    builder = DOCKERFILE.read_text(encoding="utf-8")
    builder = builder[: builder.index("AS runtime")]
    assert "uv sync --frozen --no-dev --no-install-project" in builder
    assert "type=bind,source=uv.lock" in builder


def test_the_image_runs_unprivileged_and_never_writes_bytecode_at_runtime() -> None:
    runtime = _runtime_stage()
    assert "USER 10001:10001" in runtime
    assert "PYTHONDONTWRITEBYTECODE=1" in runtime
    assert "PYTHONUNBUFFERED=1" in runtime
    # the processes share no HTTP port: compose owns the probes
    instructions = _instructions(DOCKERFILE.read_text(encoding="utf-8"))
    assert not any(line.startswith("HEALTHCHECK") for line in instructions)


def test_the_dockerignore_denies_by_default_and_allows_only_what_is_copied() -> None:
    rules = _dockerignore_rules()
    assert rules[0] == "*"
    allowed = {rule[1:] for rule in rules if rule.startswith("!")}
    assert allowed == {
        "pyproject.toml",
        "uv.lock",
        "app",
        "locales",
        "migrations",
        "alembic.ini",
    }
    for ignored in ("tests", "materials", "scripts", "openapi", "eval"):
        assert ignored not in allowed
    for pattern in (
        "**/*.md",
        "**/.env",
        "**/.env.*",
        "**/dev-keys",
        "**/*.pem",
        "**/__pycache__",
    ):
        assert pattern in rules
