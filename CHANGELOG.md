# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/). Release tags are `vX.Y.Z`; images are published as `X.Y.Z`, `X.Y` and `sha-<commit>`.

## [Unreleased]

## [1.1.0] - 2026-11-06

- Sharing: share a notebook or file by sign-in link or with named people, chat read-only in a private thread on your own limits, copy a shared notebook, attach one as live base materials.

### Changed

- **Breaking for MCP clients:** `get_marks` now returns marks grouped by subject (`{"subjects": [{"subject_id", "subject_name", "marks": [...]}]}`), for a date range or for exact semesters. A flat list of marks is gone, and a subject without marks has no entry.
- The MCP tool `get_course_media_link` now reports `idempotentHint: false`, because each call replaces the previous link.
- Bot menu buttons have icons, and their wording now matches the web apps: "Grades", "Email" and "Open the app" in English, "Уроки" in Russian.

### Added

- MCP create tools accept an optional `idempotency_key`: a retry within 24 hours returns the first result.
- `GET /v1/certificates/files/{id}/download-url`, so a certificate file can be opened from the Telegram mini app.
- The Test workflow also runs on pushes to `main`.
- MCP tools for students and course authors: flash cards, tests, notebooks, files, enrolled courses and media links. See the MCP section of the README for the list.
- `list_files` with origin `flashcards` also lists your flash card sets, your own and copies shared with you, with links. It needs `flashcards:read`.
- Media links from MCP can be listed and stopped (`GET /v1/lms/media/grants`, `DELETE /v1/lms/media/grants/{id}`).
- New MCP permissions are offered once per release and stay off until accepted. You can decide in Telegram or, new here, on the connectors page (`GET /v1/id/me/connectors/offers`, `POST /v1/id/me/connectors/offers/{id}/decision`).
- MCP call log for each person, kept for 90 days.
- Flash cards: merge sets, per-card statistics, restart a study session, review statistics and set settings.
- Certificate statistics group by a type's starred field, with an average when that field is a number.
- Open-source release: AGPL-3.0-only licence, SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue and pull request templates, CODEOWNERS, project skills for coding agents.
- `release` project skill: local CI, changelog, tagging, and image builds.
- `ty` type checker beside mypy in `scripts/style_check.sh`.
- Hydra `urls.error` points at a friendly page of the ID app.
- Lesson time blocks per weekday, Saturday and Sunday included: timetable entries accept weekdays 1 to 7 when the day has the block, and blocks of one day may not overlap. Migration `academic_0011` keeps Monday to Friday and retires old Saturday rows.

### Fixed

- A media link tied to a connector is refused if the process cannot check that connector. The check is now set up with the LMS rather than in a later step.
- A star stored on a multiple-choice certificate field is ignored, so it can no longer break the statistics.
- Gemini MCP: Gemini CLI loopback redirects can self-register, and pre-created Gemini clients list the fixed CLI redirects. Each deploy updates existing pre-created clients.
- The EMIS bell sync no longer removes a different Friday or brings back a block removed from one day.

### Known issues

- Telegram behaviour has not been checked on a real device, and Gemini sign-in has not been tried against the real service.
- MCP media links work as bearer links for 5 hours.

## [1.0.18] - 2026-11-05

### Added

- Prompt contract tests (`tests/ai/prompts`) and a real-model evaluation suite (`tests/ai/evals`, marker `real_model`, run only with `IHSP_AI_EVAL=1`).
- A normaliser that writes the Uzbek apostrophe as `ʼ` in final chat, notebook and guest answers.

### Changed

- Prompts ask for the result without the arithmetic and forbid repeating injected text.
- The answer language is set per request for every assistant. The author assistant also gets the narration guard.
- Shorter author tool descriptions.
- Notebook answers without citations no longer offer follow-up questions, unless they carry a valid action.

### Fixed

- `.env.prod.sample` documents the brand variables that the production compose file reads.
- Deployment tests match the current image versions.

### Known issues

- Answers sometimes still show worked sums, or repeat injected text while refusing it.

## [1.0.17] - 2026-11-04

### Added

- AI: projects, voice transcription, OpenUI block repair and table guidance, and safeguards for answer language, narration and tables.
- Bot: voice intake and rich answer rendering.
- Notebooks: AI flash card workspace with a hidden notebook.
- Academic: group photo export, group view and notes on future lessons.
- Identity: pre-created AI connectors with guarded MCP access.
- Dashboard: AI alert and composition wiring.
- One brand setting for user-visible names, and an export of Python dependency licences.

### Changed

- Shorter system prompts and tool descriptions, about 40% fewer input tokens per student message.
- Students use `make_document` instead of the separate document, presentation and spreadsheet tools.

### Security

- Updated joserfc, dnspython, pyasn1 and pypdf for known vulnerabilities.
- Pinned the base image and limited the secret-scanner exception for the anthropic SDK to exact files.

### Fixed

- The containers receive the OpenUI, Studio pipeline, guest and Bugsink settings.
