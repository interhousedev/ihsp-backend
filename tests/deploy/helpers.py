"""Helpers of the deployment tests: file locations and compose output."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
MATERIALS_DIR = BACKEND_DIR / "materials"
SCRIPTS_DIR = BACKEND_DIR / "scripts"
PROD_COMPOSE = MATERIALS_DIR / "docker-compose.prod.yaml"
LOCAL_COMPOSE = MATERIALS_DIR / "docker-compose.local.yaml"
PROD_ENV_SAMPLE = MATERIALS_DIR / ".env.prod.sample"
LOCAL_ENV_SAMPLE = MATERIALS_DIR / ".env.local.sample"

# Processes built from the backend image (one `python -m app <process>` each).
BACKEND_PROCESSES = (
    "migrate",
    "identity",
    "api",
    "bot",
    "mail",
    "worker",
    "scheduler",
)


def docker_compose_available() -> bool:
    """Return True when the `docker compose` plugin can be run."""
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    )
    return result.returncode == 0


requires_compose = pytest.mark.skipif(
    not docker_compose_available(), reason="docker compose is not available"
)


def compose_json(
    compose_file: Path, env_file: Path | None = None, *, profiles: bool = True
) -> dict[str, Any]:
    """Return the fully resolved compose model (all profiles) of a compose file."""
    command = ["docker", "compose"]
    if env_file is not None:
        command += ["--env-file", str(env_file)]
    command += ["-f", str(compose_file)]
    if profiles:
        command += ["--profile", "*"]
    command += ["config", "--format", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    model: dict[str, Any] = json.loads(result.stdout)
    return model


def is_one_shot(service: dict[str, Any]) -> bool:
    """Return True for a job that runs once and exits (restart policy `no`)."""
    return service.get("restart") == "no"


def published_ports(model: dict[str, Any]) -> list[tuple[str, int, int]]:
    """Return (service, host port, container port) for every published port."""
    found = []
    for name, service in model["services"].items():
        for port in service.get("ports", []):
            found.append((name, int(port["published"]), int(port["target"])))
    return found
