"""Library: tags, authors, a librarian-managed subject tree, suggestion details.

Revision ID: library_0002
Revises: library_0001
Create Date: 2026-10-10 12:00:00.000000

Creates `subjects` (the tree, seeded with a default one; subjects that older data
points at keep their ids), `authors` + `item_authors` (filled from `items.authors`),
`tags` + `item_tags`, `topics.code/archived_at` and `book_suggestions.details`.
`pg_trgm` comes from `library_0001`.
"""

import json
import uuid
from collections.abc import Sequence
from typing import Any

from app.modules.library.domain.name_keys import name_key

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "library_0002"
down_revision: str | Sequence[str] | None = "library_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAMESPACE = uuid.UUID("5d0a8c3e-6b0e-4a38-9a43-0c8d1f6c7e11")

# (slug, uz, ru, en, code, children)
Node = tuple[str, str, str, str, str, "list[Node]"]
DEFAULT_TREE: list[Node] = [
    ("mathematics", "Matematika", "Математика", "Mathematics", "ББК 22.1 · УДК 51", []),
    (
        "computer-science",
        "Informatika",
        "Информатика",
        "Computer Science",
        "ББК 32.97 · УДК 004",
        [],
    ),
    (
        "natural-sciences",
        "Tabiiy fanlar",
        "Естественные науки",
        "Natural Sciences",
        "ББК 20 · УДК 5",
        [
            ("physics", "Fizika", "Физика", "Physics", "ББК 22.3 · УДК 53", []),
            ("chemistry", "Kimyo", "Химия", "Chemistry", "ББК 24 · УДК 54", []),
            ("biology", "Biologiya", "Биология", "Biology", "ББК 28 · УДК 57", []),
            (
                "geography",
                "Geografiya",
                "География",
                "Geography",
                "ББК 26.8 · УДК 91",
                [],
            ),
        ],
    ),
    (
        "social-sciences",
        "Ijtimoiy fanlar",
        "Социальные науки",
        "Social Sciences",
        "ББК 60 · УДК 3",
        [
            ("history", "Tarix", "История", "History", "ББК 63 · УДК 94", []),
            ("law", "Huquq", "Право", "Law", "ББК 67 · УДК 34", []),
            ("philosophy", "Falsafa", "Философия", "Philosophy", "ББК 87 · УДК 1", []),
            (
                "psychology",
                "Psixologiya",
                "Психология",
                "Psychology",
                "ББК 88 · УДК 159.9",
                [],
            ),
        ],
    ),
    ("economics", "Iqtisodiyot", "Экономика", "Economics", "ББК 65 · УДК 33", []),
    (
        "languages-and-literature",
        "Til va adabiyot",
        "Языки и литература",
        "Languages and Literature",
        "ББК 81, 83 · УДК 80, 82",
        [
            (
                "uzbek",
                "Oʻzbek tili va adabiyoti",
                "Узбекский язык и литература",
                "Uzbek",
                "ББК 81.2Уз · УДК 811.512.133",
                [],
            ),
            (
                "russian",
                "Rus tili va adabiyoti",
                "Русский язык и литература",
                "Russian",
                "ББК 81.2Рус · УДК 811.161.1",
                [],
            ),
            (
                "english",
                "Ingliz tili",
                "English",
                "English",
                "ББК 81.2Англ · УДК 811.111",
                [],
            ),
            (
                "fiction",
                "Badiiy adabiyot",
                "Художественная литература",
                "Fiction",
                "ББК 84 · УДК 82-3",
                [],
            ),
        ],
    ),
    (
        "arts-and-culture",
        "Sanʻat va madaniyat",
        "Искусство и культура",
        "Arts and Culture",
        "ББК 85 · УДК 7",
        [],
    ),
    (
        "reference",
        "Maʻlumotnomalar",
        "Справочная литература",
        "Reference",
        "ББК 91 · УДК 03",
        [],
    ),
]


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _create_tables() -> None:
    op.create_table(
        "subjects",
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "name",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["library.subjects.id"],
            name=op.f("fk_subjects_parent_id_subjects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subjects")),
        sa.UniqueConstraint(
            "parent_id",
            "slug",
            name="uq_subjects_parent_id",
            postgresql_nulls_not_distinct=True,
        ),
        schema="library",
    )
    op.add_column(
        "topics",
        sa.Column("code", sa.String(length=40), nullable=True),
        schema="library",
    )
    op.add_column(
        "topics",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema="library",
    )
    op.add_column(
        "book_suggestions",
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="library",
    )
    for table, size in (("authors", 255), ("tags", 40)):
        op.create_table(
            table,
            sa.Column("name", sa.String(length=size), nullable=False),
            sa.Column("name_key", sa.String(length=size), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
            sa.UniqueConstraint("name_key", name=f"uq_{table}_name_key"),
            schema="library",
        )
        op.create_index(
            f"ix_{table}_name_key_trgm",
            table,
            ["name_key"],
            unique=False,
            schema="library",
            postgresql_using="gin",
            postgresql_ops={"name_key": "gin_trgm_ops"},
        )
    op.create_table(
        "item_authors",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_authors_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["library.authors.id"],
            name=op.f("fk_item_authors_author_id_authors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "author_id", name=op.f("pk_item_authors")),
        schema="library",
    )
    op.create_index(
        "ix_item_authors_author_id",
        "item_authors",
        ["author_id"],
        unique=False,
        schema="library",
    )
    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_tags_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["library.tags.id"],
            name=op.f("fk_item_tags_tag_id_tags"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "tag_id", name=op.f("pk_item_tags")),
        schema="library",
    )
    op.create_index(
        "ix_item_tags_tag_id", "item_tags", ["tag_id"], unique=False, schema="library"
    )


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _academic_subjects(bind: sa.Connection) -> dict[uuid.UUID, dict[str, str]]:
    """Subjects of the academic module (empty when that branch is not migrated yet)."""
    exists = bind.execute(sa.text("SELECT to_regclass('academic.subjects')")).scalar()
    if exists is None:
        return {}
    rows = bind.execute(sa.text("SELECT id, name FROM academic.subjects")).all()
    return {row[0]: {k: str(v) for k, v in (row[1] or {}).items()} for row in rows}


def _referenced_ids(bind: sa.Connection) -> set[uuid.UUID]:
    """Subject ids that library rows already point at."""
    found: set[uuid.UUID] = set()
    for table in (
        "item_subjects",
        "topics",
        "reading_lists",
        "book_plans",
        "external_field_map",
    ):
        rows = bind.execute(
            # nosemgrep: avoid-sqlalchemy-text -- fixed table tuple, no input
            sa.text(f"SELECT DISTINCT subject_id FROM library.{table}")  # noqa: S608
        )
        found.update(row[0] for row in rows if row[0] is not None)
    return found


def _tree_rows(
    academic: dict[uuid.UUID, dict[str, str]],
) -> tuple[list[dict[str, Any]], set[uuid.UUID]]:
    """Rows of the default tree; an academic subject of the same name lends its id."""
    by_name: dict[str, uuid.UUID] = {}
    for sid, names in academic.items():
        for value in names.values():
            if value.strip():
                by_name.setdefault(_norm(value), sid)
    used: set[uuid.UUID] = set()
    rows: list[dict[str, Any]] = []

    def add(node: Node, parent: uuid.UUID | None, position: int) -> None:
        slug, uz, ru, en, code, children = node
        names = {"uz": uz, "ru": ru, "en": en}
        matched = next(
            (by_name[_norm(v)] for v in (ru, en, uz) if _norm(v) in by_name), None
        )
        sid = (
            matched if matched and matched not in used else uuid.uuid5(NAMESPACE, slug)
        )
        used.add(sid)
        rows.append(
            {
                "id": sid,
                "parent_id": parent,
                "name": json.dumps(names, ensure_ascii=False),
                "slug": slug,
                "code": code,
                "position": position,
            }
        )
        for index, child in enumerate(children):
            add(child, sid, index)

    for index, node in enumerate(DEFAULT_TREE):
        add(node, None, index)
    return rows, used


def _slug_of(names: dict[str, str], sid: uuid.UUID) -> str:
    words = "".join(c if c.isalnum() else " " for c in names.get("en", "").lower())
    return ("-".join(words.split()) or f"subject-{str(sid)[:8]}")[:70]


def _leftover_rows(
    academic: dict[uuid.UUID, dict[str, str]],
    wanted: set[uuid.UUID],
    taken_slugs: set[str],
    first_position: int,
) -> list[dict[str, Any]]:
    """Root rows for academic subjects that library rows use but the tree lacks."""
    rows: list[dict[str, Any]] = []
    for sid in sorted(wanted, key=str):
        names = academic.get(sid)
        if not names:
            continue
        base = _slug_of(names, sid)
        slug, number = base, 2
        while slug in taken_slugs:
            slug = f"{base}-{number}"
            number += 1
        taken_slugs.add(slug)
        rows.append(
            {
                "id": sid,
                "parent_id": None,
                "name": json.dumps(names, ensure_ascii=False),
                "slug": slug,
                "code": None,
                "position": first_position + len(rows),
            }
        )
    return rows


def _seed_subjects(bind: sa.Connection) -> None:
    """The default tree plus the subjects that older rows point at (same ids)."""
    academic = _academic_subjects(bind)
    rows, used = _tree_rows(academic)
    taken = {row["slug"] for row in rows if row["parent_id"] is None}
    rows += _leftover_rows(
        academic, _referenced_ids(bind) - used, taken, len(DEFAULT_TREE)
    )
    insert = sa.text(
        "INSERT INTO library.subjects (id, parent_id, name, slug, code, position) "
        "VALUES (:id, :parent_id, CAST(:name AS jsonb), :slug, :code, :position)"
    )
    # Parents first: the foreign key needs them in the table before their children.
    for row in sorted(rows, key=lambda r: r["parent_id"] is not None):
        bind.execute(insert, row)


def _move_authors(bind: sa.Connection) -> None:
    """One author row per person in `items.authors`, linked in the title page order."""
    items = bind.execute(
        sa.text("SELECT id, authors FROM library.items WHERE cardinality(authors) > 0")
    ).all()
    author_ids: dict[str, uuid.UUID] = {}
    for item_id, authors in items:
        position = 0
        linked: set[uuid.UUID] = set()
        for raw in authors:
            name = " ".join(str(raw).split())[:255]
            key = name_key(name)
            if not key:
                continue
            if key not in author_ids:
                author_ids[key] = uuid.uuid4()
                bind.execute(
                    sa.text(
                        "INSERT INTO library.authors (id, name, name_key) "
                        "VALUES (:id, :name, :key)"
                    ),
                    {"id": author_ids[key], "name": name, "key": key},
                )
            author_id = author_ids[key]
            if author_id in linked:
                continue
            linked.add(author_id)
            bind.execute(
                sa.text(
                    "INSERT INTO library.item_authors (item_id, author_id, position) "
                    "VALUES (:item, :author, :position)"
                ),
                {"item": item_id, "author": author_id, "position": position},
            )
            position += 1


def upgrade() -> None:
    """Upgrade schema."""
    _create_tables()
    bind = op.get_bind()
    _seed_subjects(bind)
    _move_authors(bind)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("item_tags", schema="library")
    op.drop_table("item_authors", schema="library")
    op.drop_table("tags", schema="library")
    op.drop_table("authors", schema="library")
    op.drop_column("book_suggestions", "details", schema="library")
    op.drop_column("topics", "archived_at", schema="library")
    op.drop_column("topics", "code", schema="library")
    op.drop_table("subjects", schema="library")
