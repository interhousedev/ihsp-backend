"""Scanner exceptions stay narrow and the base image stays pinned."""

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SDK_PREFIX = r"^/?app/\.venv/lib/python3\.13/site-packages/anthropic/"


def test_trivy_secret_allow_rules_name_exact_sdk_files() -> None:
    config = yaml.safe_load((ROOT / "trivy-secret.yaml").read_text())
    rules = config["allow-rules"]
    assert set(config) == {"allow-rules"}
    assert rules
    for rule in rules:
        path = rule["path"]
        assert "regex" not in rule
        assert path.startswith(SDK_PREFIX) and path.endswith("$")
        tail = path.removeprefix(SDK_PREFIX).removesuffix("$")
        assert not re.search(r"[*+?\[\]()|]", tail.replace(r"\.", "")), path


def test_dockerfile_base_images_are_pinned_by_digest() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    images = re.findall(r"^FROM (\S+)", dockerfile, flags=re.MULTILINE)
    assert images
    assert all("@sha256:" in image for image in images)


def test_joserfc_floor_excludes_cve_2026_119284() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "joserfc>=1.7.6" in project["dependencies"]
