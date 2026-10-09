"""Demo library: a librarian, six books, a collection, a reading list, two materials.

Everything goes through the library use cases (and the files API for the PDF
blobs), so the audit trail, search index and notices are those of real use. The
files are tiny PDFs built here; nothing is added to the repository. Every step looks
the thing up by its title first, so a second run changes nothing.
"""

from dataclasses import dataclass
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.seed.users import TEACHERS, ensure_librarian
from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.domain.catalogue_books import BookData
from app.modules.library.domain.entities import SubjectLink, TopicLink
from app.modules.library.domain.enums import (
    FileFormat,
    Importance,
    ItemLanguage,
    ItemType,
    ListScope,
    ListStatus,
    MaterialLicence,
    Rights,
    SubjectRole,
    Visibility,
)
from app.modules.library.domain.reading_list import EntryDraft
from app.modules.library.domain.taxonomy_errors import ListForbiddenError
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.features import Feature, is_enabled

import structlog

log = structlog.get_logger(__name__)

STUDENT_LOGIN = "abdullayev.alisher"
TEACHER_LOGIN = TEACHERS[0].login
MATH, UZBEK = 101, 105  # EMIS subject ids of the demo structure
LOCALE = "uz"

TOPIC_NAMES = {
    UZBEK: {"uz": "Klassik nasr", "ru": "Классическая проза", "en": "Classic prose"},
    MATH: {
        "uz": "Hosila va integral",
        "ru": "Производная и интеграл",
        "en": "Derivatives and integrals",
    },
}
COLLECTION_TITLE = {
    "uz": "Litsey tanlovi",
    "ru": "Выбор лицея",
    "en": "Lyceum picks",
}
LIST_TITLE = "Hosila: haftalik o'qish (Производная: чтение на неделю)"
TEACHER_MATERIAL = "Hosila: mashqlar varaqasi (Лист задач)"
STUDENT_MATERIAL = "Integral formulalari: konspekt (Formula sheet)"


@dataclass(frozen=True, slots=True)
class BookSpec:
    """One demo book."""

    subject: int
    title: str
    authors: tuple[str, ...]
    year: int
    language: ItemLanguage
    kind: ItemType
    death_year: int | None = None  # set: public domain, visible to everyone


BOOKS: tuple[BookSpec, ...] = (
    BookSpec(
        UZBEK,
        "O'tkan kunlar",
        ("Abdulla Qodiriy",),
        1926,
        ItemLanguage.UZ_LATN,
        ItemType.FICTION,
        death_year=1938,
    ),
    BookSpec(
        UZBEK,
        "Mehrobdan chayon",
        ("Abdulla Qodiriy",),
        1929,
        ItemLanguage.UZ_LATN,
        ItemType.FICTION,
        death_year=1938,
    ),
    BookSpec(
        UZBEK,
        "Xamsa: tanlangan sahifalar",
        ("Alisher Navoiy",),
        1483,
        ItemLanguage.UZ_LATN,
        ItemType.POETRY,
        death_year=1501,
    ),
    BookSpec(
        MATH,
        "Сборник задач по математическому анализу",
        ("Б. П. Демидович",),
        1990,
        ItemLanguage.RU,
        ItemType.PROBLEM_BOOK,
    ),
    BookSpec(
        MATH,
        "Calculus: Early Transcendentals",
        ("James Stewart",),
        2015,
        ItemLanguage.EN,
        ItemType.TEXTBOOK,
    ),
    BookSpec(
        MATH,
        "Algebra va analiz asoslari",
        ("Mualliflar jamoasi",),
        2022,
        ItemLanguage.UZ_LATN,
        ItemType.TEXTBOOK,
    ),
)


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with the ASCII text on it (a few hundred bytes)."""
    stream = f"BT /F1 14 Tf 50 780 Td ({text}) Tj ET".encode("ascii")
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page,
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )
    return bytes(out)


async def _store_pdf(
    container: Container, owner: UUID, purpose: FilePurpose, name: str, text: str
) -> UUID:
    """Store the PDF as a library file and run the text extraction inline."""
    ref = await container.files.public.store_bytes(
        owner_id=owner,
        scope=FileScope.LIBRARY,
        purpose=purpose,
        name=name,
        data=tiny_pdf(text),
    )
    await container.files.process_file.execute(ref.id)
    return ref.id


async def _ensure_topics(
    container: Container, librarian: Actor, subjects: dict[int, UUID]
) -> dict[int, UUID]:
    taxonomy = container.library.taxonomy
    topics: dict[int, UUID] = {}
    for emis_id, names in TOPIC_NAMES.items():
        subject_id = subjects[emis_id]
        existing = await taxonomy.list_manage_topics.execute(
            librarian, subject_id=subject_id
        )
        found = next((t for t in existing if t.name.get("en") == names["en"]), None)
        if found is None:
            found = await taxonomy.create_topic.execute(
                librarian, subject_id=subject_id, name=names
            )
        topics[emis_id] = found.id
    return topics


async def _ensure_book(
    container: Container,
    librarian: Actor,
    spec: BookSpec,
    subjects: dict[int, UUID],
    topics: dict[int, UUID],
) -> UUID:
    catalogue = container.library.catalogue
    page = await catalogue.list_books.execute(librarian, q=spec.title, limit=20)
    for row in page.items:
        if row.card.title == spec.title and row.card.id is not None:
            return row.card.id
    public = spec.death_year is not None
    basis: dict[str, object] = (
        {"rule": "author_life", "author_death_year": spec.death_year}
        if public
        else {"reference": "Demo catalogue of IHSP"}
    )
    data = BookData(
        title=spec.title,
        authors=list(spec.authors),
        language=spec.language,
        year_published=spec.year,
        type=spec.kind,
        years_of_study=[1],
        subjects=[SubjectLink(subjects[spec.subject], role=SubjectRole.TEXTBOOK)],
        topics=[TopicLink(topics[spec.subject])],
        rights=Rights.PUBLIC_DOMAIN if public else Rights.OFFICIAL,
        rights_basis=basis,
        visibility=Visibility.PUBLIC if public else Visibility.LYCEUM,
        download_allowed=public,
    )
    book = await catalogue.create_book.execute(librarian, data)
    assert book.card.id is not None
    file_id = await _store_pdf(
        container,
        librarian.user_id,
        FilePurpose.LIBRARY_BOOK,
        f"{book.card.slug}.pdf",
        f"IHSP library demo copy of book {spec.year}",
    )
    await catalogue.attach_book_file.execute(
        librarian,
        book.card.id,
        file_id=file_id,
        file_format=FileFormat.PDF,
        is_primary=True,
    )
    await catalogue.process_item_file.execute(book.card.id, file_id)
    await catalogue.publish_book.execute(librarian, book.card.id)
    log.info("seed_library_book_created", title=spec.title)
    return book.card.id


async def _ensure_collection(
    container: Container, librarian: Actor, item_ids: list[UUID]
) -> None:
    taxonomy = container.library.taxonomy
    existing = await taxonomy.list_manage_collections.execute(librarian)
    if any(c.title.get("en") == COLLECTION_TITLE["en"] for c in existing):
        return
    await taxonomy.create_collection.execute(
        librarian, title=COLLECTION_TITLE, published=True, item_ids=item_ids
    )
    log.info("seed_library_collection_created")


async def _group_of(
    container: Container, user_id: UUID, groups: dict[str, UUID]
) -> UUID | None:
    queries = container.academic.schedule.queries
    for group_id in groups.values():
        if user_id in await queries.group_user_ids([group_id]):
            return group_id
    return None


async def _ensure_reading_list(
    container: Container,
    teacher: Actor,
    librarian: Actor,
    *,
    subject_id: UUID,
    group_id: UUID,
    entries: list[EntryDraft],
) -> None:
    taxonomy = container.library.taxonomy
    for owner in (teacher, librarian):
        mine = await taxonomy.list_reading_lists.execute(owner, mine=True)
        if any(card.title == LIST_TITLE for card in mine):
            return
    for owner in (teacher, librarian):  # a teacher without lessons now: the librarian
        try:
            created = await taxonomy.create_reading_list.execute(
                owner,
                title=LIST_TITLE,
                description="Weekly reading on derivatives for the group.",
                scope=ListScope.GROUPS,
                subject_id=subject_id,
                group_ids=[group_id],
                status=ListStatus.PUBLISHED,
            )
        except ListForbiddenError:
            continue
        await taxonomy.replace_list_entries.execute(owner, created.card.id, entries)
        log.info("seed_library_reading_list_created")
        return


async def _ensure_material(
    container: Container, actor: Actor, data: MaterialData, text: str
) -> None:
    """Upload a material as the actor; teachers publish at once, students queue."""
    materials = container.library.materials
    mine = await materials.list_my_uploads.execute(
        actor, status=None, cursor=None, limit=50, locale=LOCALE
    )
    if any(row.item.title == data.title for row in mine.items):
        return
    draft = await materials.create_material.execute(actor, data, locale=LOCALE)
    item_id = draft.card.id
    assert item_id is not None
    file_id = await _store_pdf(
        container, actor.user_id, FilePurpose.LIBRARY_MATERIAL, "material.pdf", text
    )
    await materials.attach_material_files.execute(
        actor, item_id, [file_id], locale=LOCALE
    )
    await materials.submit_material.execute(actor, item_id, locale=LOCALE)
    await container.library.catalogue.process_item_file.execute(item_id, file_id)
    log.info("seed_library_material_created", title=data.title)


async def seed_library(
    container: Container, subject_ids: dict[int, UUID], group_ids: dict[str, UUID]
) -> None:
    """Add the demo library once; skipped when `FEATURES__LIBRARY` is off."""
    if not is_enabled(container.settings, Feature.LIBRARY):
        log.info("seed_library_skipped", reason="FEATURES__LIBRARY is off")
        return
    directory = container.identity.directory
    teacher_user = await directory.user_by_login(TEACHER_LOGIN)
    student_user = await directory.user_by_login(STUDENT_LOGIN)
    if teacher_user is None or student_user is None:
        log.warning("seed_library_skipped", reason="demo teacher or student missing")
        return
    librarian = Actor(
        user_id=await ensure_librarian(container), roles=frozenset({Role.LIBRARIAN})
    )
    teacher = Actor(user_id=teacher_user.id, roles=frozenset({Role.TEACHER}))
    student = Actor(user_id=student_user.id, roles=frozenset({Role.STUDENT}))
    subjects = {MATH: subject_ids[MATH], UZBEK: subject_ids[UZBEK]}

    topics = await _ensure_topics(container, librarian, subjects)
    book_ids = [
        await _ensure_book(container, librarian, spec, subjects, topics)
        for spec in BOOKS
    ]
    await _ensure_collection(container, librarian, book_ids)

    group_id = await _group_of(container, student.user_id, group_ids)
    if group_id is not None:
        math_books = [book_ids[i] for i, s in enumerate(BOOKS) if s.subject == MATH]
        importance = (Importance.ESSENTIAL, Importance.RECOMMENDED, Importance.FURTHER)
        entries = [
            EntryDraft(importance=level, item_id=item_id, week_label="Week 1")
            for level, item_id in zip(importance, math_books, strict=True)
        ]
        await _ensure_reading_list(
            container,
            teacher,
            librarian,
            subject_id=subjects[MATH],
            group_id=group_id,
            entries=entries,
        )

    def material(
        title: str, description: str, kind: ItemType, licence: MaterialLicence
    ) -> MaterialData:
        return MaterialData(
            title=title,
            description=description,
            subject_ids=(subjects[MATH],),
            topic_ids=(topics[MATH],),
            years_of_study=(1,),
            type=kind,
            language=ItemLanguage.UZ_LATN,
            licence=licence,
            attested=True,
        )

    await _ensure_material(
        container,
        teacher,
        material(
            TEACHER_MATERIAL,
            "Ten exercises on the rules of derivatives.",
            ItemType.WORKSHEET,
            MaterialLicence.CC_BY_NC,
        ),
        "IHSP library demo worksheet on derivatives",
    )
    await _ensure_material(
        container,
        student,
        material(
            STUDENT_MATERIAL,
            "My notes on the basic integrals, for review.",
            ItemType.FORMULA_SHEET,
            MaterialLicence.ALL_RIGHTS_RESERVED,
        ),
        "IHSP library demo formula sheet on integrals",
    )
