"""Export and erasure of a user's personal data.

A user may request a copy of their data (``privacy.build_export``: a ZIP of every
module's rows and their own uploaded files, valid for 7 days, one per 24 hours) and
the deletion of the account (``DELETE /v1/id/me`` records a ``pending_review``
request; an administrator approves it, which starts the 30-day window; at its end
``FinalizeAccountDeletions`` runs ``privacy.erase_owner``).

Every module describes its user-keyed tables in
``<module>/infrastructure/personal_data.py`` (``SPECS``). ``tests/privacy`` checks
that every table with a user column is listed there or below as an exemption.

Coverage (schema.table: treatment, reason):

- ``academic.homework_todos``: erase, personal to-do list
- ``academic.student_sync_jobs``: erase, EMIS sync queue
- ``academic.emis_attendance``: retain, school record
- ``academic.excuse_messages``: retain, school record
- ``academic.excuses``: retain, school record
- ``academic.homework_submissions``: retain, school record
- ``academic.marks``: retain, school record
- ``academic.results``: retain, school record
- ``academic.temporary_marks``: retain, school record
- ``academic.work_offs``: retain, school record
- ``academic.work_off_templates``: retain, school record
- ``academic.students``: retain, school roster
- ``academic.lessons``: retain, timetable reference
- ``academic.timetable_entries``: retain, timetable reference
- ``academic.groups``: retain, class head reference
- ``admin.ai_access_restrictions``: erase
- ``admin.limit_extensions``: erase
- ``admin.broadcasts``: retain, staff announcement authorship
- ``ai.chat_messages``: erase
- ``ai.chats``: erase
- ``ai.project_files``: erase
- ``ai.projects``: erase
- ``ai.usage_events``: nullify, statistics kept without the user
- ``ai.flashcard_reviews``: erase
- ``ai.flashcards``: erase
- ``ai.flashcard_sets``: erase
- ``certificates.entries``: retain, school record
- ``dashboard.layouts``: erase
- ``faces.passages``: erase, gate passages
- ``faces.device_calls``: nullify, device statistics
- ``faces.face_profiles``: erase, metadata exported; embedding never
- ``feedback.responses``: erase
- ``feedback.items``: erase
- ``files.file_shares``: erase, erased by files.delete_owner
- ``files.files``: erase, erased by files.delete_owner
- ``id.sessions``: erase
- ``id.personal_tokens``: erase, metadata only
- ``id.mcp_connectors``: erase, metadata only
- ``id.mcp_call_log``: erase
- ``id.mcp_scope_offers``: erase
- ``id.passkeys``: erase, names only
- ``id.user_factors``: erase, flags only
- ``id.telegram_links``: erase
- ``id.login_cues``: nullify, registration cue, EMIS login encrypted
- ``id.audit_events``: retain, audit trail
- ``id.users``: anonymise, anonymised by purge_deleted_users
- ``knowledge.entries``: erase
- ``legal.acceptances``: retain, proof of consent; address and device are cleared
- ``library.annotations``: erase, erased by library.delete_owner
- ``library.reading_progress``: erase, erased by library.delete_owner
- ``library.shelf_entries``: erase, erased by library.delete_owner
- ``library.book_suggestions``: erase
- ``library.sanctions``: erase
- ``library.reading_lists``: erase
- ``library.item_events``: retain, catalogue history
- ``library.item_reports``: retain, moderation record
- ``library.items``: retain, catalogue
- ``library.material_details``: retain, catalogue
- ``library.item_authors``: retain, catalogue
- ``library.lesson_item_refs``: retain, teacher plan
- ``links.emis_hide_rules``: erase
- ``links.links``: erase
- ``lms.course_staff``: retain, course record
- ``lms.enrollments``: retain, course record
- ``lms.step_states``: retain, course record
- ``lms.test_attempts``: retain, course record
- ``mail.mail_messages``: erase
- ``notebooks.artifact_progress``: erase, erased by notebooks.delete_owner
- ``notebooks.notebook_shares``: erase, erased by notebooks.delete_owner
- ``notebooks.subject_default_materials``: erase, erased by notebooks.delete_owner
- ``notebooks.messages``: erase, erased by notebooks.delete_owner
- ``notebooks.presentation_plans``: erase, erased by notebooks.delete_owner
- ``notebooks.artifacts``: erase, erased by notebooks.delete_owner
- ``notebooks.sources``: erase, erased by notebooks.delete_owner
- ``notebooks.notebooks``: erase, erased by notebooks.delete_owner
- ``notify.notifications``: erase
- ``notify.push_subscriptions``: erase, devices only
- ``notify.course_broadcasts``: retain, staff announcement authorship
- ``onboarding.onboarding_progress``: erase
- ``privacy.exports``: erase, archives in storage are deleted by privacy.erase_owner
- ``privacy.erasure_requests``: retain, record that the lyceum handled the request

Exempt (no user column, or derived data that is removed with its source):

- ``posts.bot_user_modes``: a Telegram chat id, not an account; no personal content.
- ``vectors.embeddings``: derived from the owner's rows, removed with them.
- notebook passages and document caches: derived from the owner's sources, removed
  with the notebooks (``notebooks.delete_owner``).
"""
