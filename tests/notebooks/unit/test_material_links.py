"""Web materials: the files and article images a page offers (DOM scan)."""

from app.modules.notebooks.infrastructure.material_links import (
    extract_candidates,
    reputable,
)

PAGE = "https://bio.example.org/lessons/photosynthesis"
HTML = """
<html><head><link rel="icon" href="/favicon.png">
<script>var a='<a href="x.pdf">';</script></head>
<body>
<header><img src="/img/logo.png" alt="Site logo">
<a href="/brochure.pdf">Brochure</a></header>
<nav><a href="/menu.pdf">Menu</a></nav>
<article>
  <h1>Photosynthesis</h1>
  <p>Read the full lecture notes:
     <a href="/files/lecture-5.pdf">Lecture 5 notes</a>.</p>
  <p>Slides <a href="https://cdn.example.org/slides.pptx#p2">here</a> and data
     <a href="/data/leaves.xlsx">leaf measurements</a>.</p>
  <figure><img src="/img/chloroplast.png" width="800" height="600" alt="Chloroplast">
    <figcaption>Structure of a chloroplast</figcaption></figure>
  <img src="/img/tiny.png" width="32" height="32" alt="bullet">
  <img src="data:image/png;base64,AAAA" alt="inline">
  <img src="/img/diagram.svg" alt="vector">
  <img src="https://ads.tracker.net/pixel.png" alt="">
  <img class="author-avatar" src="/img/me.jpg" alt="Author">
  <img src="https://evil.example.com/cycle.jpg" width="900" alt="Calvin cycle">
  <a href="https://www.nasa.gov/report.pdf">NASA report</a>
  <a href="https://random-blog.net/copy.pdf">Mirror</a>
  <audio src="/audio/lecture.mp3"></audio>
  <a href="javascript:void(0)">x.pdf</a>
  <a href="ftp://bio.example.org/old.pdf">Old</a>
</article>
<footer><a href="/privacy.pdf">Privacy</a></footer>
</body></html>
"""


def _urls(limit: int = 20) -> list[str]:
    return [c.url for c in extract_candidates(HTML, PAGE, limit=limit)]


def test_documents_audio_and_article_images_are_found_in_order() -> None:
    """Documents first, then audio, then images; fragments dropped."""
    assert _urls() == [
        "https://bio.example.org/files/lecture-5.pdf",
        "https://cdn.example.org/slides.pptx",
        "https://bio.example.org/data/leaves.xlsx",
        "https://www.nasa.gov/report.pdf",
        "https://bio.example.org/audio/lecture.mp3",
        "https://bio.example.org/img/chloroplast.png",
    ]


def test_chrome_icons_trackers_tiny_data_and_foreign_sites_are_skipped() -> None:
    """Header, nav, footer, logos, avatars, pixels, SVG, data URIs, other sites."""
    urls = " ".join(_urls())
    for skipped in (
        "brochure",
        "menu",
        "privacy",
        "logo",
        "tiny",
        "data:",
        "svg",
        "pixel",
        "me.jpg",
        "evil.example.com",
        "random-blog",
        "ftp:",
        "javascript",
    ):
        assert skipped not in urls


def test_titles_and_context_are_kept_for_the_triage() -> None:
    """Link text, alt text and the caption describe a candidate."""
    found = {c.url: c for c in extract_candidates(HTML, PAGE, limit=20)}
    lecture = found["https://bio.example.org/files/lecture-5.pdf"]
    assert lecture.kind == "document"
    assert lecture.title == "Lecture 5 notes"
    assert "lecture notes" in lecture.context
    image = found["https://bio.example.org/img/chloroplast.png"]
    assert image.kind == "image"
    assert "Structure of a chloroplast" in image.context


def test_the_cap_limits_the_candidates() -> None:
    """At most `limit`; 0 finds nothing."""
    assert len(_urls(limit=2)) == 2
    assert extract_candidates(HTML, PAGE, limit=0) == []


def test_broken_markup_keeps_what_was_found() -> None:
    """Unclosed tags do not lose the candidates."""
    found = extract_candidates(
        '<div><p><a href="/a.pdf">A<div><a href="b.docx">B', PAGE, limit=5
    )
    assert [c.url.rsplit("/", 1)[-1] for c in found] == ["a.pdf", "b.docx"]


def test_reputable_hosts() -> None:
    """The page's own site and education or government hosts."""
    assert reputable("cdn.example.org", "bio.example.org")
    assert reputable("www.mit.edu", "bio.example.org")
    assert reputable("uz.wikipedia.org", "bio.example.org")
    assert not reputable("example.com", "bio.example.org")
