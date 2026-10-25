"""academic init

Revision ID: academic_0001
Revises:
Create Date: 2026-10-07 17:00:22.190838

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "academic_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("academic",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS academic")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "groups",
        sa.Column("emis_group_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("current_semester", sa.SmallInteger(), nullable=True),
        sa.Column("emis_curriculum_id", sa.Integer(), nullable=True),
        sa.Column(
            "subject_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("curator_id", sa.Uuid(), nullable=True),
        sa.Column("head_student_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "archived",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("emis_group_id", name="uq_groups_emis_group_id"),
        schema="academic",
    )
    op.create_index(
        "ix_groups_slug_active",
        "groups",
        ["slug"],
        unique=True,
        schema="academic",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "rooms",
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("pin", sa.String(length=16), nullable=False),
        sa.Column(
            "pin_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "archived",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            ["academic.rooms.id"],
            name=op.f("fk_rooms_merged_into_id_rooms"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
        sa.UniqueConstraint("slug", name="uq_rooms_slug"),
        schema="academic",
    )
    op.create_table(
        "subjects",
        sa.Column("emis_subject_id", sa.Integer(), nullable=True),
        sa.Column("name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("short_name", sa.String(length=64), nullable=True),
        sa.Column(
            "can_be_divided",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subjects")),
        sa.UniqueConstraint("emis_subject_id", name="uq_subjects_emis_subject_id"),
        schema="academic",
    )
    op.create_table(
        "sync_runs",
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "done",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
        schema="academic",
    )
    op.create_index(
        "ix_sync_runs_started_at",
        "sync_runs",
        ["started_at"],
        unique=False,
        schema="academic",
    )
    op.create_table(
        "terms",
        sa.Column("academic_year", sa.String(length=16), nullable=False),
        sa.Column("half", sa.SmallInteger(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column(
            "non_study_days",
            sa.ARRAY(sa.Date()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "moved_days",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "bells",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        postgresql.ExcludeConstraint(
            (sa.literal_column("daterange(starts_on, ends_on, '[]')"), "&&"),
            using="gist",
            name="ex_terms_no_overlap",
        ),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f("ck_terms_dates")),
        sa.CheckConstraint("half IN (1, 2)", name=op.f("ck_terms_half")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terms")),
        sa.UniqueConstraint(
            "academic_year", "half", name="uq_terms_academic_year_half"
        ),
        schema="academic",
    )
    op.create_table(
        "students",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("subgroup", sa.SmallInteger(), nullable=True),
        sa.Column("subgroup_set_by", sa.Uuid(), nullable=True),
        sa.Column("subgroup_set_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "left",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("left_at", sa.Date(), nullable=True),
        sa.Column(
            "left_reason",
            sa.Enum(
                "graduated",
                "expelled",
                "transferred",
                "other",
                name="left_reason",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("calendar_token_hash", sa.String(length=64), nullable=True),
        sa.Column("backfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sync_failures",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("sync_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("subgroup IN (1, 2)", name=op.f("ck_students_subgroup")),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["academic.groups.id"],
            name=op.f("fk_students_group_id_groups"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_students")),
        sa.UniqueConstraint(
            "calendar_token_hash", name="uq_students_calendar_token_hash"
        ),
        schema="academic",
    )
    op.create_index(
        "ix_students_group_id_status",
        "students",
        ["group_id", "status"],
        unique=False,
        schema="academic",
    )
    op.create_table(
        "timetable_entries",
        sa.Column("term_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("period", sa.SmallInteger(), nullable=False),
        sa.Column(
            "week_parity",
            sa.Enum(
                "every",
                "odd",
                "even",
                name="week_parity",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'every'"),
            nullable=False,
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=True),
        sa.Column("room_id", sa.Uuid(), nullable=True),
        sa.Column("audience", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "cardinality(audience) > 0",
            name=op.f("ck_timetable_entries_audience_not_empty"),
        ),
        sa.CheckConstraint("period >= 1", name=op.f("ck_timetable_entries_period")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name=op.f("ck_timetable_entries_valid_range"),
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 1 AND 6", name=op.f("ck_timetable_entries_weekday")
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["academic.rooms.id"],
            name=op.f("fk_timetable_entries_room_id_rooms"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["academic.subjects.id"],
            name=op.f("fk_timetable_entries_subject_id_subjects"),
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["academic.terms.id"],
            name=op.f("fk_timetable_entries_term_id_terms"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_timetable_entries")),
        schema="academic",
    )
    op.create_index(
        "ix_timetable_entries_audience",
        "timetable_entries",
        ["audience"],
        unique=False,
        schema="academic",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_timetable_entries_teacher_id",
        "timetable_entries",
        ["teacher_id"],
        unique=False,
        schema="academic",
    )
    op.create_index(
        "ix_timetable_entries_term_id_weekday_period",
        "timetable_entries",
        ["term_id", "weekday", "period"],
        unique=False,
        schema="academic",
    )
    op.create_table(
        "lessons",
        sa.Column("timetable_entry_id", sa.Uuid(), nullable=True),
        sa.Column("origin_date", sa.Date(), nullable=True),
        sa.Column("term_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("period", sa.SmallInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=True),
        sa.Column("room_id", sa.Uuid(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("audience", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "cancelled",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'scheduled'"),
            nullable=False,
        ),
        sa.Column(
            "is_overridden",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("homework_text", sa.Text(), nullable=True),
        sa.Column("homework_due_date", sa.Date(), nullable=True),
        sa.Column(
            "homework_due_auto",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("homework_by", sa.Uuid(), nullable=True),
        sa.Column("homework_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("homework_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attendance_roster", sa.ARRAY(sa.Uuid()), nullable=True),
        sa.Column("attendance_absent", sa.ARRAY(sa.Uuid()), nullable=True),
        sa.Column(
            "attendance_excused", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "attendance_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("attendance_by", sa.Uuid(), nullable=True),
        sa.Column("attendance_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attendance_source",
            sa.Enum(
                "bot",
                "staff",
                "admin",
                name="attendance_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        postgresql.ExcludeConstraint(
            (sa.column("room_id"), "="),
            (sa.literal_column("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=sa.text("status = 'scheduled'"),
            using="gist",
            name="ex_lessons_room_no_overlap",
        ),
        postgresql.ExcludeConstraint(
            (sa.column("teacher_id"), "="),
            (sa.literal_column("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=sa.text("status = 'scheduled'"),
            using="gist",
            name="ex_lessons_teacher_no_overlap",
        ),
        sa.CheckConstraint(
            "(attendance_roster IS NULL) = (attendance_absent IS NULL)",
            name=op.f("ck_lessons_attendance_pair"),
        ),
        sa.CheckConstraint(
            "attendance_absent <@ attendance_roster",
            name=op.f("ck_lessons_attendance_subset"),
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_lessons_time_range")),
        sa.ForeignKeyConstraint(
            ["room_id"], ["academic.rooms.id"], name=op.f("fk_lessons_room_id_rooms")
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["academic.subjects.id"],
            name=op.f("fk_lessons_subject_id_subjects"),
        ),
        sa.ForeignKeyConstraint(
            ["term_id"], ["academic.terms.id"], name=op.f("fk_lessons_term_id_terms")
        ),
        sa.ForeignKeyConstraint(
            ["timetable_entry_id"],
            ["academic.timetable_entries.id"],
            name=op.f("fk_lessons_timetable_entry_id_timetable_entries"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lessons")),
        sa.UniqueConstraint(
            "timetable_entry_id", "origin_date", name="uq_lessons_entry_origin_date"
        ),
        schema="academic",
    )
    op.create_index(
        "ix_lessons_attendance_absent",
        "lessons",
        ["attendance_absent"],
        unique=False,
        schema="academic",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_lessons_attendance_roster",
        "lessons",
        ["attendance_roster"],
        unique=False,
        schema="academic",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_lessons_audience",
        "lessons",
        ["audience"],
        unique=False,
        schema="academic",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_lessons_date", "lessons", ["date"], unique=False, schema="academic"
    )
    op.create_index(
        "ix_lessons_ends_at", "lessons", ["ends_at"], unique=False, schema="academic"
    )
    op.create_index(
        "ix_lessons_starts_at",
        "lessons",
        ["starts_at"],
        unique=False,
        schema="academic",
    )
    op.create_index(
        "ix_lessons_teacher_id_date",
        "lessons",
        ["teacher_id", "date"],
        unique=False,
        schema="academic",
    )
    op.create_table(
        "results",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("value", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("lesson_avg", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("midterm_avg", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("final_avg", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("emis_rating", sa.SmallInteger(), nullable=True),
        sa.Column(
            "marks_count",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("emis_hash", sa.String(length=128), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "emis_rating BETWEEN 0 AND 100", name=op.f("ck_results_emis_rating")
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_results_student_id_students"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["academic.subjects.id"],
            name=op.f("fk_results_subject_id_subjects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_results")),
        sa.UniqueConstraint(
            "student_id",
            "semester",
            "subject_id",
            name="uq_results_student_semester_subject",
            postgresql_nulls_not_distinct=True,
        ),
        schema="academic",
    )
    op.create_table(
        "homework_todos",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "char_length(note) <= 1000", name=op.f("ck_homework_todos_note_length")
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["academic.lessons.id"],
            name=op.f("fk_homework_todos_lesson_id_lessons"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_homework_todos_student_id_students"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_homework_todos")),
        sa.UniqueConstraint(
            "student_id", "lesson_id", name="uq_homework_todos_student_lesson"
        ),
        schema="academic",
    )
    op.create_index(
        "ix_homework_todos_lesson_id",
        "homework_todos",
        ["lesson_id"],
        unique=False,
        schema="academic",
    )
    op.create_table(
        "marks",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "lesson",
                "midterm",
                "final",
                name="type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.SmallInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "ordinal", sa.SmallInteger(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("ordinal >= 1", name=op.f("ck_marks_ordinal")),
        sa.CheckConstraint("semester BETWEEN 1 AND 4", name=op.f("ck_marks_semester")),
        sa.CheckConstraint("value BETWEEN 2 AND 5", name=op.f("ck_marks_value")),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["academic.lessons.id"],
            name=op.f("fk_marks_lesson_id_lessons"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_marks_student_id_students"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["academic.subjects.id"],
            name=op.f("fk_marks_subject_id_subjects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marks")),
        sa.UniqueConstraint(
            "student_id",
            "subject_id",
            "semester",
            "type",
            "date",
            "value",
            "ordinal",
            name="uq_marks_natural_key",
        ),
        schema="academic",
    )
    op.create_index(
        "ix_marks_lesson_id", "marks", ["lesson_id"], unique=False, schema="academic"
    )
    op.create_index(
        "ix_marks_student_id_date",
        "marks",
        ["student_id", "date"],
        unique=False,
        schema="academic",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_marks_student_id_date", table_name="marks", schema="academic")
    op.drop_index("ix_marks_lesson_id", table_name="marks", schema="academic")
    op.drop_table("marks", schema="academic")
    op.drop_index(
        "ix_homework_todos_lesson_id", table_name="homework_todos", schema="academic"
    )
    op.drop_table("homework_todos", schema="academic")
    op.drop_table("results", schema="academic")
    op.drop_index("ix_lessons_teacher_id_date", table_name="lessons", schema="academic")
    op.drop_index("ix_lessons_starts_at", table_name="lessons", schema="academic")
    op.drop_index("ix_lessons_ends_at", table_name="lessons", schema="academic")
    op.drop_index("ix_lessons_date", table_name="lessons", schema="academic")
    op.drop_index(
        "ix_lessons_audience",
        table_name="lessons",
        schema="academic",
        postgresql_using="gin",
    )
    op.drop_index(
        "ix_lessons_attendance_roster",
        table_name="lessons",
        schema="academic",
        postgresql_using="gin",
    )
    op.drop_index(
        "ix_lessons_attendance_absent",
        table_name="lessons",
        schema="academic",
        postgresql_using="gin",
    )
    op.drop_table("lessons", schema="academic")
    op.drop_index(
        "ix_timetable_entries_term_id_weekday_period",
        table_name="timetable_entries",
        schema="academic",
    )
    op.drop_index(
        "ix_timetable_entries_teacher_id",
        table_name="timetable_entries",
        schema="academic",
    )
    op.drop_index(
        "ix_timetable_entries_audience",
        table_name="timetable_entries",
        schema="academic",
        postgresql_using="gin",
    )
    op.drop_table("timetable_entries", schema="academic")
    op.drop_index(
        "ix_students_group_id_status", table_name="students", schema="academic"
    )
    op.drop_table("students", schema="academic")
    op.drop_table("terms", schema="academic")
    op.drop_index("ix_sync_runs_started_at", table_name="sync_runs", schema="academic")
    op.drop_table("sync_runs", schema="academic")
    op.drop_table("subjects", schema="academic")
    op.drop_table("rooms", schema="academic")
    op.drop_index(
        "ix_groups_slug_active",
        table_name="groups",
        schema="academic",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_table("groups", schema="academic")
    # The btree_gist extension stays: it is database-wide and may be used elsewhere.
    op.execute("DROP SCHEMA IF EXISTS academic CASCADE")
