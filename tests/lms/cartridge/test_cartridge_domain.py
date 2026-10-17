"""Cartridge parsing, URL rewriting, QTI, archive safety, export integrity, round trip."""  # noqa: E501

import io
import json
import zipfile
from typing import Any
from uuid import uuid4

from app.modules.lms.domain.cartridge.archive import CartridgeArchive, Limits
from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError
from app.modules.lms.domain.cartridge.exporter import (
    ExportCourse,
    ExportFile,
    ExportSection,
    export_cartridge,
    validate_cartridge,
)
from app.modules.lms.domain.cartridge.html_markdown import html_to_markdown
from app.modules.lms.domain.cartridge.importer import ImportPlan, plan_import
from app.modules.lms.domain.cartridge.manifest import parse_manifest
from app.modules.lms.domain.step_content import StepContent
from tests.lms.cartridge.fixtures import (
    PNG,
    build_zip,
    canvas_like,
    manifest,
    ocw_like,
    openstax_like,
)

import pytest


def _plan(data: bytes) -> ImportPlan:
    return plan_import(CartridgeArchive(data))


@pytest.mark.parametrize("version", ["1.1", "1.2", "1.3"])
def test_manifest_versions(version: str) -> None:
    text = manifest(
        version,
        "T",
        '<item identifier="m"><title>M</title>'
        '<item identifier="i" identifierref="r"><title>P</title></item></item>',
        '<resource identifier="r" type="webcontent" href="a/p.html" '
        'xml:base="x/"><file href="a/p.html"/></resource>',
    )
    parsed = parse_manifest(text.encode())
    assert parsed.version == version
    assert parsed.title == "T"
    assert parsed.items[0].children[0].identifierref == "r"
    assert parsed.resources["r"].href == "x/a/p.html"


def test_manifest_refuses_entities() -> None:
    bad = b'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "b">]><manifest/>'
    with pytest.raises(CartridgeInvalidError):
        parse_manifest(bad)


def test_openstax_nested_structure() -> None:
    plan = _plan(openstax_like())
    assert [s.title for s in plan.sections] == ["Chapter 1", "Chapter 2", "Review"]
    assert len(plan.sections[0].steps) == 3
    markdown = plan.sections[0].steps[0].blocks[0]["markdown"]
    assert "![Figure](ihsp-asset:0)" in markdown and "$$x^2$$" in markdown
    assert plan.assets[0] == "resources/fig1.png"
    assert plan.report.quizzes == 1 and plan.report.questions == 5


def test_filebase_rewriting_both_spellings_and_missing() -> None:
    plan = _plan(ocw_like())
    lecture = plan.sections[0].steps[0]
    text = lecture.blocks[0]["markdown"]
    assert text.count("ihsp-asset:0") == 2  # $IMS-CC-FILEBASE$ and %24...%24
    assert plan.assets == ["web_resources/lec1.pdf"]
    assert "next lecture" in text and "lecture2" not in text  # page link -> text
    assert lecture.blocks[1] == {
        "type": "video",
        "source": "link",
        "url": "https://www.youtube.com/embed/abc",
    }
    assert "| A | B |" in text
    assert any(i.kind == "file" for i in plan.report.items)


def test_canvas_extras_reported() -> None:
    plan = _plan(canvas_like())
    assert plan.title == "Canvas Course"
    kinds = {i.kind for i in plan.report.items}
    assert {"discussion", "lti", "question-bank", "x-unknown/thing"} <= kinds
    assert plan.sections[-1].title == "Other materials"
    tool = next(s for s in plan.sections[0].steps if s.title == "Tool")
    assert "https://tool.example/launch" in tool.blocks[0]["markdown"]


def test_qti_mapping() -> None:
    plan = _plan(openstax_like())
    block = plan.sections[-1].steps[0].blocks[0]
    assert block["config"] == {"max_attempts": 2}
    q = block["questions"]
    assert [x["type"] for x in q] == ["single", "single", "multiple", "text", "free"]
    assert [o["correct"] for o in q[0]["options"]] == [False, True]
    assert q[0]["explanation"] == "Count."
    assert "ihsp-asset:" in q[0]["prompt"]
    assert [o["text"] for o in q[1]["options"] if o["correct"]] == ["True"]
    assert [o["correct"] for o in q[2]["options"]] == [True, True, False]
    assert q[3]["answer"] == {"accepted": ["Paris", "paris"]}
    StepContent.model_validate({"title": "x", "blocks": [block]})


def test_html_conversion_drops_scripts_and_keeps_text() -> None:
    result = html_to_markdown(
        "<p>A <script>x()</script><strong>b</strong> <a href='http://e.x'>l</a></p>",
        lambda url, kind: url,
    )
    assert result.markdown == "A **b** [l](http://e.x)"


def _zip(entries: dict[str, bytes]) -> bytes:
    return build_zip({"imsmanifest.xml": "<manifest/>", **entries})


@pytest.mark.parametrize(
    "name", ["../evil.txt", "/etc/passwd", "a/../../b", "C:/x", "a\\..\\..\\b"]
)
def test_zip_slip_rejected(name: str) -> None:
    with pytest.raises(CartridgeInvalidError) as caught:
        CartridgeArchive(_zip({name: b"x"}))
    assert caught.value.params["reason"] == "unsafe-path"


def test_zip_bomb_rejected() -> None:
    with pytest.raises(CartridgeInvalidError) as caught:
        CartridgeArchive(_zip({"big.txt": b"\0" * (4 * 1024 * 1024)}))
    assert caught.value.params["reason"] == "bomb"


def test_total_size_and_count_caps() -> None:
    data = _zip({f"f{i}.txt": b"abc" for i in range(5)})
    with pytest.raises(CartridgeInvalidError):
        CartridgeArchive(data, Limits(members=3))
    with pytest.raises(CartridgeInvalidError):
        CartridgeArchive(data, Limits(total_bytes=10))
    with pytest.raises(CartridgeInvalidError):
        CartridgeArchive(b"not a zip")
    with pytest.raises(CartridgeInvalidError):
        CartridgeArchive(build_zip({"a.txt": b"x"}))  # no manifest


def _course() -> tuple[ExportCourse, str]:
    image = uuid4()
    blocks = [
        {"type": "text", "markdown": f"# Intro\n\nSee ![pic](/files/{image}) **now**"},
        {
            "type": "video",
            "source": "link",
            "url": "https://youtu.be/x",
            "caption": "V",
        },
        {
            "type": "test",
            "config": {"max_attempts": 3},
            "questions": [
                {
                    "type": "single",
                    "prompt": "Pick",
                    "options": [
                        {"text": "a", "correct": True},
                        {"text": "b"},
                    ],
                },
                {"type": "text", "prompt": "Say", "answer": {"accepted": ["hi"]}},
                {"type": "free", "prompt": "Essay"},
            ],
        },
        {"type": "flashcards", "cards": [{"front": "F", "back": "B"}]},
    ]
    content = StepContent.model_validate({"title": "Step one", "blocks": blocks})
    course = ExportCourse(
        title="Algebra",
        description="Desc",
        sections=[
            ExportSection("Week 1", [content.model_dump(mode="json")]),
            ExportSection("Week 2", [{"title": "Empty", "blocks": []}]),
        ],
        files={image: ExportFile("pic one.png", PNG)},
    )
    return course, str(image)


def test_export_manifest_integrity() -> None:
    course, _ = _course()
    result = export_cartridge(course)
    assert validate_cartridge(result.data) == []
    names = zipfile.ZipFile(io.BytesIO(result.data)).namelist()
    assert any(n.startswith("quizzes/") for n in names)
    assert any(n.startswith("web_resources/files/") for n in names)
    assert any(n.startswith("links/") for n in names)


def test_validate_finds_problems() -> None:
    bad = build_zip(
        {
            "imsmanifest.xml": manifest(
                "1.3",
                "T",
                '<item identifier="a" identifierref="nope"><title>x</title></item>',
                '<resource identifier="a" type="bogus" href="gone.html">'
                '<file href="gone.html"/></resource>',
            ),
            "stray.txt": b"x",
        }
    )
    problems = validate_cartridge(bad)
    joined = " ".join(problems)
    for part in ("duplicate", "nope", "bogus", "missing file", "unlisted"):
        assert part in joined


def _strip_ids(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, dict):
        return {k: _strip_ids(v) for k, v in value.items() if k != "id"}
    if isinstance(value, list):
        return [_strip_ids(v) for v in value]
    return value


def test_round_trip_with_extension_is_exact() -> None:
    course, image = _course()
    plan = _plan(export_cartridge(course).data)
    assert plan.title == "Algebra" and plan.description == "Desc"
    assert [s.title for s in plan.sections] == ["Week 1", "Week 2"]
    original = _strip_ids(course.sections[0].steps[0]["blocks"])
    imported = plan.sections[0].steps[0].blocks
    swapped = json.loads(
        json.dumps(imported).replace("ihsp-asset:0", f"/files/{image}")
    )
    assert _strip_ids(swapped) == original


def test_round_trip_without_extension_keeps_structure() -> None:
    course, _ = _course()
    data = export_cartridge(course).data
    source = zipfile.ZipFile(io.BytesIO(data))
    stripped = build_zip(
        {n: source.read(n) for n in source.namelist() if not n.startswith("ihsp/")}
    )
    plan = _plan(stripped)
    week = plan.sections[0]
    assert [s.title for s in week.steps] == ["Step one", "V", "Step one"]
    assert "# Intro" in week.steps[0].blocks[0]["markdown"]
    assert "![pic](ihsp-asset:0)" in week.steps[0].blocks[0]["markdown"]
    assert week.steps[1].blocks[0]["url"] == "https://youtu.be/x"
    questions = week.steps[2].blocks[0]["questions"]
    assert [q["type"] for q in questions] == ["single", "text", "free"]
    assert week.steps[2].blocks[0]["config"] == {"max_attempts": 3}
