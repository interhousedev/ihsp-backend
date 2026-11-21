"""The ORM metadata holds exactly the tables of spec -> Models and the modules."""

from app.shared.db import models  # noqa: F401  (imports every module's ORM package)
from app.shared.db.base import Base

EXPECTED_TABLES = {
    # admission (86)
    "admission.admission_stats",
    "admission.affordability_checks",
    "admission.aid_policies",
    "admission.audit_events",
    "admission.campuses",
    "admission.catalog_proposals",
    "admission.checklist_items",
    "admission.comments",
    "admission.costs_of_attendance",
    "admission.courses",
    "admission.deadlines",
    "admission.deck_decisions",
    "admission.document_attachments",
    "admission.document_versions",
    "admission.documents",
    "admission.eligibility_rules",
    "admission.entitlements",
    "admission.essay_feedback",
    "admission.essay_invites",
    "admission.essay_reviews",
    "admission.essay_versions",
    "admission.exemplar_essays",
    "admission.essays",
    "admission.facts",
    "admission.goal_milestones",
    "admission.institutions",
    "admission.item_interviews",
    "admission.item_metrics",
    "admission.item_opportunity_links",
    "admission.items",
    "admission.list_entries",
    "admission.milestones",
    "admission.officer_settings",
    "admission.places",
    "admission.preferences",
    "admission.profile_words",
    "admission.profile_words_history",
    "admission.profiles",
    "admission.programs",
    "admission.proof_claims",
    "admission.proofs",
    "admission.reminder_prefs",
    "admission.reminders",
    "admission.requirements",
    "admission.review_feedback",
    "admission.reviews",
    "admission.routes",
    "admission.runtime_settings",
    "admission.safety_facts",
    "admission.scholarships",
    "admission.sources",
    "admission.staff_assignments",
    "admission.staff_roles",
    "admission.staff_saved_views",
    "admission.transcript_requests",
    "admission.admission_student_chunks",
    "admission.app_reviews",
    "admission.kb_articles",
    "admission.calendar_feeds",
    "admission.calendar_reminders",
    "admission.career_majors",
    "admission.career_plans",
    "admission.career_questions",
    "admission.essay_ideas",
    "admission.exam_dates",
    "admission.opportunities",
    "admission.opportunity_ai_plans",
    "admission.opportunity_plan_entries",
    "admission.opportunity_submissions",
    "admission.opportunity_taxonomy",
    "admission.student_preferences",
    "admission.tasks",
    "admission.test_catalog",
    "admission.test_scores",
    "admission.application_outcomes",
    "admission.consultations",
    "admission.memory_notes",
    "admission.opportunity_comment_reports",
    "admission.opportunity_comments",
    "admission.orgs",
    "admission.profile_details",
    "admission.quiz_answers",
    "admission.supp_prompts",
    "admission.uni_chats",
    "admission.uni_default_prompts",
    "admission.uni_web_cache",
    "admission.university_decisions",
    # id (8)
    "id.users",
    "id.sessions",
    "id.telegram_links",
    "id.mcp_connectors",
    "id.mcp_call_log",
    "id.mcp_scope_offers",
    "id.audit_events",
    "id.user_factors",
    "id.passkeys",
    "id.login_cues",
    "id.personal_tokens",
    # academic (19)
    "academic.terms",
    "academic.groups",
    "academic.students",
    "academic.subjects",
    "academic.rooms",
    "academic.timetable_entries",
    "academic.lessons",
    "academic.homework_todos",
    "academic.homework_submissions",
    "academic.marks",
    "academic.results",
    "academic.sync_runs",
    "academic.assessments",
    "academic.group_curriculum",
    "academic.group_curriculum_subject",
    "academic.emis_attendance",
    "academic.work_off_templates",
    "academic.work_offs",
    "academic.student_sync_jobs",
    "academic.temporary_marks",
    "academic.excuse_templates",
    "academic.excuses",
    "academic.excuse_messages",
    # files (1), links (1)
    "files.files",
    "files.file_shares",
    "files.file_share_links",
    "links.emis_hide_rules",
    "links.links",
    # ai (5: chats and messages of module ai; sets, cards and the review log of
    # module flashcards)
    "ai.chats",
    "ai.chat_messages",
    "ai.flashcard_sets",
    "ai.flashcards",
    "ai.flashcard_reviews",
    "ai.usage_events",
    "ai.web_pages",
    "ai.web_queries",
    "ai.projects",
    "ai.project_files",
    "ai.telegram_topics",
    "ai.tracing_settings",
    "ai.prompt_versions",
    # notify (2), admin (1), mail (1)
    "notify.notifications",
    "notify.push_subscriptions",
    "notify.course_broadcasts",
    "admin.broadcasts",
    "admin.platform_settings",
    "admin.limit_extensions",
    "admin.ai_access_restrictions",
    "admin.telegram_bots",
    "admin.telegram_bot_members",
    "mail.mail_messages",
    # lms (10)
    "lms.courses",
    "lms.course_staff",
    "lms.course_steps",
    "lms.step_revisions",
    "lms.course_versions",
    "lms.enrollments",
    "lms.step_states",
    "lms.test_attempts",
    "lms.media_grants",
    "lms.access_rules",
    # notebooks (12)
    "notebooks.notebooks",
    "notebooks.sources",
    "notebooks.passages",
    "notebooks.documents",
    "notebooks.document_aliases",
    "notebooks.document_guides",
    "notebooks.shared_summaries",
    "notebooks.shared_artifacts",
    "notebooks.messages",
    "notebooks.artifacts",
    "notebooks.artifact_assets",
    "notebooks.artifact_progress",
    "notebooks.source_labels",
    "notebooks.source_label_links",
    "notebooks.source_label_runs",
    "notebooks.subject_default_materials",
    "notebooks.presentation_plans",
    "notebooks.notebook_shares",
    "notebooks.notebook_share_links",
    "notebooks.notebook_linked_sets",
    # library (25)
    "library.subjects",
    "library.item_tags",
    "library.tags",
    "library.item_authors",
    "library.authors",
    "library.items",
    "library.external_details",
    "library.book_details",
    "library.material_details",
    "library.item_files",
    "library.item_pages",
    "library.topics",
    "library.item_subjects",
    "library.item_topics",
    "library.collections",
    "library.collection_items",
    "library.reading_lists",
    "library.reading_list_items",
    "library.external_feeds",
    "library.external_field_map",
    "library.item_reports",
    "library.item_events",
    "library.sanctions",
    "library.book_suggestions",
    "library.shelf_entries",
    "library.reading_progress",
    "library.annotations",
    "library.reader_markup",
    "library.book_plans",
    "library.lesson_item_refs",
    "library.item_stats",
    # vectors (1)
    "vectors.embeddings",
    # dashboard (1)
    "dashboard.layouts",
    # certificates (3)
    "certificates.types",
    "certificates.entries",
    "certificates.entry_files",
    # knowledge (1)
    "knowledge.entries",
    # posts (2)
    "posts.posts",
    "posts.bot_user_modes",
    # feedback (2)
    "feedback.items",
    "feedback.responses",
    # legal (3)
    "legal.documents",
    "legal.acceptances",
    "legal.purpose_consents",
    # faces (4)
    "faces.face_profiles",
    "faces.devices",
    "faces.device_calls",
    "faces.passages",
    # onboarding (1)
    "onboarding.onboarding_progress",
    # privacy (2)
    "privacy.erasure_requests",
    "privacy.exports",
    "admission.activity_days",
    "admission.essay_gallery",
    "admission.essay_practice",
    "admission.essay_short_answers",
    "admission.essay_slots",
    "admission.fit_preferences",
    "admission.honor_dismissals",
    "admission.idea_fits",
    "admission.profession_plans",
    "admission.prompt_group_labels",
    "admission.season_overrides",
    "admission.staff_pins",
    "admission.today_snoozes",
    "ai.ai_requests",
    "ai.connectors",
    "ai.pipeline_routes",
    "ai.prompt_defaults",
}


def test_metadata_contains_every_table_of_the_models_readme() -> None:
    """spec -> Models plus the later modules (247 tables)."""
    actual = {table.fullname for table in Base.metadata.tables.values()}

    assert len(EXPECTED_TABLES) == 247
    assert actual == EXPECTED_TABLES


def test_every_table_has_a_primary_key_and_timestamps() -> None:
    """Every table has a primary key, created_at and updated_at."""
    for table in Base.metadata.tables.values():
        assert list(table.primary_key.columns), table.fullname
        assert "created_at" in table.c, table.fullname
        assert "updated_at" in table.c, table.fullname


def test_students_primary_key_is_user_id() -> None:
    """academic.students has no id column; user_id is the primary key."""
    table = Base.metadata.tables["academic.students"]

    assert [column.name for column in table.primary_key.columns] == ["user_id"]
    assert "id" not in table.c


def test_no_foreign_key_crosses_a_schema_except_inside_ai() -> None:
    """Foreign keys stay inside their schema (flashcards share schema ai)."""
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema == table.schema, foreign_key


def test_flashcards_branch_has_no_foreign_key_to_ai_tables() -> None:
    """The flashcards migration branch does not depend on the ai branch."""
    ai_tables = {"ai.chats", "ai.chat_messages"}
    for name in ("ai.flashcard_sets", "ai.flashcards", "ai.flashcard_reviews"):
        for foreign_key in Base.metadata.tables[name].foreign_keys:
            assert foreign_key.column.table.fullname not in ai_tables


def test_reserved_attribute_names_are_mapped_to_the_documented_columns() -> None:
    """The metadata columns are reached as ``meta`` in Python."""
    for name in ("id.audit_events", "files.files"):
        assert "metadata" in Base.metadata.tables[name].c
    assert "meta" in Base.metadata.tables["mail.mail_messages"].c
