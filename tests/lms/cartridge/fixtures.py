"""Cartridges built in memory that mimic real ones (OpenStax, MIT OCW, Canvas)."""

import io
import zipfile
from pathlib import Path

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01"
    b"\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

NS = {
    "1.1": "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1",
    "1.2": "http://www.imsglobal.org/xsd/imsccv1p2/imscp_v1p1",
    "1.3": "http://www.imsglobal.org/xsd/imsccv1p3/imscp_v1p1",
}
QTI_TYPE = {
    "1.1": "imsqti_xmlv1p2/imscc_xmlv1p1/assessment",
    "1.2": "imsqti_xmlv1p2/imscc_xmlv1p2/assessment",
    "1.3": "imsqti_xmlv1p2/imscc_xmlv1p3/assessment",
}


def build_zip(members: dict[str, bytes | str]) -> bytes:
    """Zip the members (str is UTF-8 encoded)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data.encode() if isinstance(data, str) else data)
    return buffer.getvalue()


def manifest(version: str, title: str, org: str, resources: str) -> str:
    """A manifest of the given CC version."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="M1" xmlns="{NS[version]}"
  xmlns:lomimscc="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest">
  <metadata><schema>IMS Common Cartridge</schema>
    <schemaversion>{version}.0</schemaversion>
    <lomimscc:lom><lomimscc:general>
      <lomimscc:title><lomimscc:string>{title}</lomimscc:string></lomimscc:title>
      <lomimscc:description><lomimscc:string>About {title}</lomimscc:string>
      </lomimscc:description>
    </lomimscc:general></lomimscc:lom>
  </metadata>
  <organizations><organization identifier="O1" structure="rooted-hierarchy">
    <item identifier="LearningModules">{org}</item>
  </organization></organizations>
  <resources>{resources}</resources>
</manifest>"""


QUIZ = (Path(__file__).parent / "data" / "quiz.xml").read_text()


def page(title: str, body: str) -> str:
    """An HTML page."""
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


def openstax_like() -> bytes:
    """CC 1.1: chapters -> sections -> pages, images by relative path, a quiz."""
    org = []
    resources = []
    members: dict[str, bytes | str] = {}
    for chapter in (1, 2):
        sections = []
        for section in (1, 2, 3):
            ident = f"p{chapter}{section}"
            href = f"contents/ch{chapter}/s{section}.html"
            members[href] = page(
                f"{chapter}.{section}",
                f"<h2>Section {chapter}.{section}</h2><p>Text with "
                f'<img src="../../resources/fig{chapter}.png" alt="Figure"/> and '
                '<math display="block"><semantics><mi>x</mi>'
                '<annotation encoding="application/x-tex">x^2</annotation>'
                "</semantics></math></p><ul><li>One</li><li>Two</li></ul>",
            )
            resources.append(
                f'<resource identifier="{ident}" type="webcontent" href="{href}">'
                f'<file href="{href}"/></resource>'
            )
            sections.append(
                f'<item identifier="i{ident}" identifierref="{ident}">'
                f"<title>{chapter}.{section} Page</title></item>"
            )
        org.append(
            f'<item identifier="c{chapter}"><title>Chapter {chapter}</title>'
            f'<item identifier="g{chapter}"><title>Group</title>{"".join(sections)}</item>'  # noqa: E501
            "</item>"
        )
        members[f"resources/fig{chapter}.png"] = PNG
        resources.append(
            f'<resource identifier="f{chapter}" type="webcontent" '
            f'href="resources/fig{chapter}.png"><file href="resources/fig{chapter}.png"/>'  # noqa: E501
            "</resource>"
        )
    members["quiz/assessment.xml"] = QUIZ
    members["quiz/img/q.png"] = PNG
    resources.append(
        f'<resource identifier="quiz1" type="{QTI_TYPE["1.1"]}">'
        '<file href="quiz/assessment.xml"/><file href="quiz/img/q.png"/></resource>'
    )
    org.append(
        '<item identifier="c3"><title>Review</title>'
        '<item identifier="iq" identifierref="quiz1"><title>Quiz</title></item></item>'
    )
    members["imsmanifest.xml"] = manifest(
        "1.1", "College Physics", "".join(org), "".join(resources)
    )
    return build_zip(members)


def ocw_like(version: str = "1.2") -> bytes:
    """MIT OCW style: lecture pages with $IMS-CC-FILEBASE$ PDFs, links, a video."""
    members: dict[str, bytes | str] = {
        "web_resources/lec1.pdf": b"%PDF-1.4 lecture",
        "pages/lecture1.html": page(
            "Lecture 1",
            '<p>Read <a href="$IMS-CC-FILEBASE$/lec1.pdf">the notes</a> and '
            '<a href="%24IMS-CC-FILEBASE%24/lec1.pdf">again</a>.</p>'
            '<iframe src="//www.youtube.com/embed/abc"></iframe>'
            '<p><a href="lecture2.html">next lecture</a> '
            '<a href="missing.pdf">gone</a></p>'
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>",
        ),
        "pages/lecture2.html": page("Lecture 2", "<p>Second</p>"),
        "links/wl1.xml": (
            '<?xml version="1.0"?><webLink xmlns="http://www.imsglobal.org/xsd/'
            'imsccv1p1/imswl_v1p1"><title>OCW site</title>'
            '<url href="https://ocw.mit.edu/"/></webLink>'
        ),
    }
    resources = (
        '<resource identifier="r1" type="webcontent" href="pages/lecture1.html">'
        '<file href="pages/lecture1.html"/><dependency identifierref="pdf"/></resource>'
        '<resource identifier="r2" type="webcontent" href="pages/lecture2.html">'
        '<file href="pages/lecture2.html"/></resource>'
        '<resource identifier="pdf" type="webcontent" href="web_resources/lec1.pdf">'
        '<file href="web_resources/lec1.pdf"/></resource>'
        f'<resource identifier="wl" type="imswl_xmlv{version.replace(".", "p")}">'
        '<file href="links/wl1.xml"/></resource>'
    )
    org = (
        '<item identifier="m1"><title>Lectures</title>'
        '<item identifier="a" identifierref="r1"><title>Lecture 1</title></item>'
        '<item identifier="b" identifierref="r2"><title>Lecture 2</title></item>'
        '<item identifier="c" identifierref="wl"><title>Course site</title></item>'
        "</item>"
    )
    members["imsmanifest.xml"] = manifest(version, "Linear Algebra", org, resources)
    return build_zip(members)


def canvas_like() -> bytes:
    """CC 1.3 from Canvas: discussion, LTI, question bank, unreferenced wiki page."""
    members: dict[str, bytes | str] = {
        "d1/topic.xml": (
            '<?xml version="1.0"?><topic xmlns="http://www.imsglobal.org/xsd/'
            'imsccv1p3/imsdt_v1p3"><title>Introduce yourself</title>'
            '<text texttype="text/html">&lt;p&gt;Say hi &lt;img src="%24IMS-CC-'
            'FILEBASE%24/hello.png"&gt;&lt;/p&gt;</text></topic>'
        ),
        "web_resources/hello.png": PNG,
        "lti/tool.xml": (
            '<?xml version="1.0"?><cartridge_basiclti_link xmlns="http://www.'
            'imsglobal.org/xsd/imslticc_v1p3" xmlns:blti="http://www.imsglobal.org/'
            'xsd/imsbasiclti_v1p0"><blti:title>Tool</blti:title>'
            "<blti:launch_url>https://tool.example/launch</blti:launch_url>"
            "</cartridge_basiclti_link>"
        ),
        "wiki_content/orphan.html": page("Orphan page", "<p>Not in a module</p>"),
        "bank/bank.xml": QUIZ,
        "course_settings/course_settings.xml": (
            '<?xml version="1.0"?><course><title>Canvas Course</title></course>'
        ),
    }
    resources = (
        '<resource identifier="dt" type="imsdt_xmlv1p3"><file href="d1/topic.xml"/>'
        "</resource>"
        '<resource identifier="hello" type="webcontent" '
        'href="web_resources/hello.png"><file href="web_resources/hello.png"/>'
        "</resource>"
        '<resource identifier="lti" type="imsbasiclti_xmlv1p3">'
        '<file href="lti/tool.xml"/></resource>'
        '<resource identifier="wiki" type="webcontent" href="wiki_content/orphan.html">'
        '<file href="wiki_content/orphan.html"/></resource>'
        '<resource identifier="bank" type="imsqti_xmlv1p2/imscc_xmlv1p3/question-bank">'
        '<file href="bank/bank.xml"/></resource>'
        '<resource identifier="odd" type="x-unknown/thing"><file href="d1/topic.xml"/>'
        "</resource>"
    )
    org = (
        '<item identifier="m1"><title>Week 1</title>'
        '<item identifier="h"><title>Read first</title></item>'
        '<item identifier="a" identifierref="dt"><title>Intro</title></item>'
        '<item identifier="b" identifierref="lti"><title>Tool</title></item>'
        '<item identifier="c" identifierref="bank"><title>Bank</title></item>'
        '<item identifier="d" identifierref="odd"><title>Odd</title></item>'
        "</item>"
    )
    text = manifest("1.3", "", org, resources)
    members["imsmanifest.xml"] = text
    return build_zip(members)
