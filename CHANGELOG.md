# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/). Release tags are `vX.Y.Z`; images are published as `X.Y.Z`, `X.Y` and `sha-<commit>`.

## [Unreleased]

### Changed

- `GET /v1/me/today` is faster: the student, the next study day, the homework and the lesson items are resolved once per request, and all teachers come from one identity lookup (response unchanged).

### Added

- Login cues kill switch `IHSP_FEATURES__LOGIN_CUES` (off by default: admin and public cue routes answer 404, the admin page leaves the app map), `POST /v1/admin/login-cues/bulk-delete`, and the public `GET /v1/public/client-config` (feature flags and `IHSP_DOCS__*` links).
- A group added without an EMIS id is adopted by a normalized name match (case, spaces, hyphens, Cyrillic look-alikes), and the first EMIS link of a group kicks the new task `academic.repull_group`: it forces the curriculum and a full timetable backfill and queues a sync for every other member with a working EMIS link. Later registrations do nothing extra.
- Step-up and other one-time codes: a failed Telegram send is retried once, falls back to the verified recovery email, and when nothing delivers the code and cooldown are dropped and the request answers 503 `id/otp-delivery-failed` instead of a silent 202.
- Documentation site (MkDocs Material, published to GitHub Pages by `.github/workflows/docs.yml`) with guides for personal tokens and entrance devices; the `docs` dependency group holds `mkdocs-material`.
- Planner: each target of `GET /v1/me/marks/subjects/{id}/planner` has `paths`, up to five minimal ways to reach it (`extra_lesson_fives`, lowest `midterm` and `final`).
- Student card: `GET /v1/me/student-card`, `POST /v1/me/student-card/tokens` (a two-minute token, only its SHA-256 is kept in Redis) and the public `GET /v1/public/student-cards/{token}` with `/photo` (404 `student_card_not_found`); `iht-web` needs `bun run sync:openapi`.
- Honours: `GET /v1/me/honours` (red diploma, gold and silver medal rules with the blocking marks), admin rules under `honours` of `PUT /v1/admin/settings`, `GET /v1/me/emis/rating-book` (the EMIS rating book link); the EMIS profile gains the institution name, school certificate serial and number, direction and speciality; `iht-web` needs `bun run sync:openapi`.

## [1.4.0] - 2026-11-11

### Added

- Homework submissions: a student hands in files (`PUT/GET/DELETE /v1/me/homework/{lesson_id}/submission`, files uploaded through `/v1/files`), the teacher sees who submitted, who is late or missing, with download links (`GET /v1/staff/lessons/{lesson_id}/homework/submissions`); MCP tools `submit_homework`, `withdraw_homework_submission` (scope `homework:submit`) and `list_homework_submissions` (teacher scope `homework:read`); `get_homework` shows the submission status. New table `academic.homework_submissions`; `iht-web` needs `bun run sync:openapi`.
- MCP tool `upload_file` (scope `files:write`) on the student and teacher servers: a ChatGPT file parameter or base64 content becomes a ready file in the caller's Files; unsafe URLs are refused before any connection.
- Bot: the sign-in screen for an unlinked account offers two buttons, one to sign in with an existing ID account and one to register a new account with EMIS.

## [1.3.0] - 2026-11-11

### Added

- LMS MCP tool set: teachers can build whole courses from ChatGPT (`build_course`, AI drafts, block and question editing, `publish`, `restore_version`, staff, students, progress, attempts and `override_score`).
- Teachers MCP server at `/mcp/teacher` with tools over the teacher's own schedule, groups, journal, homework, temporary marks, ПК/ИК assessments and unfinished work, plus the teacher AI tools when the AI backend is wired.
- Teacher AI tools (questions, handouts, work checks, AI-authorship estimate with a caveat, lesson plan templates and plans) in the notebooks module; new AI tasks `teacher_questions`, `teacher_handout`, `teacher_work_check`, `teacher_ai_check`, `teacher_lesson_plan`. Templates and plans are the teacher's own files.
- Studio slides: a research step per planned slide and free pictures from Wikimedia Commons (credit shown on the slide and in the pptx notes), new image, stats, timeline and comparison layouts, and a build stage (`planning`, `researching`, `images`, `designing`) on the artifact. Settings `IHSP_NOTEBOOKS__SLIDES_*`; `iht-web` needs `bun run sync:openapi`.

### Changed

- Teachers are LMS administrators by default: new teachers (admin creation, EMIS sync, seed) get `lms_admin`, and migration `identity_0013` grants it once to every existing teacher. `ChangeRoles` lets `lms_admin` be granted to a teacher or an administrator; revoking `admin` removes `lms_admin` only from users who are not teachers. The admin role editor follows the same rule.
- Web search asks Parallel first (`IHSP_PARALLEL__*`, shared Redis limiter) and falls back to Exa on an error, a timeout, a rate limit or an empty answer; a deep search asks both and merges the pages by URL. The usage ledger and the logs name the provider.
- Parallel web search works without a key: in live mode without `IHSP_PARALLEL__API_KEY` it uses Parallel's free MCP endpoint (`IHSP_PARALLEL__MCP_URL`, `IHSP_PARALLEL__KEYLESS`, `IHSP_PARALLEL__KEYLESS_MAX_QPS`), with Exa as the fallback; a keyed setup still uses the Parallel API.
- New subject and lesson notebooks keep a title suffix (`notebooks.subject_title_suffix`, migration `notebooks_0016`) and show the subject's current name in the reader's language when opened (`NotebookTitles`, `ScheduleQueries.subject_titles`); a renamed notebook keeps its typed title.
- Teacher AI tools write questions and handouts in the language of the topic when no language is given.

### Fixed

- The Hydra discovery metadata lists the teacher MCP scopes, and the production env sample documents `IHSP_PARALLEL__MODE` and `IHSP_PARALLEL__API_KEY`.

## [1.2.1] - 2026-11-11

### Changed

- `POST /v1/admin/vault/unseal` takes only `{key}`: the `otp_code` field and the step-up code requirement are removed (administrator role, rate limit and audit stay). Other admin step-up flows are unchanged. `iht-web` needs `bun run sync:openapi`.

### Fixed

- `GET /v1/me/files` answered 500: the excuse attachment lookup used `.overlap` on a generic `ARRAY` column; it now uses the `&&` operator with a bound `uuid[]`.

## [1.2.0] - 2026-11-10

### Added

- Bot: with `IHSP_BOT__WIDGETS_ENABLED=true`, OpenUI blocks in private-chat answers are sent as Telegram widgets (Bot API 10.4) that follow the Telegram theme; group chats, unsupported or oversized blocks and API errors keep the Markdown rendering.
- Bot: every answer with OpenUI blocks gets a "See visualization" Mini App button (a URL button in groups) that opens the share app, for clients without widget support.
- Guest bot: answers may contain OpenUI blocks, sent as widgets in private chats (or degraded to Markdown), with a Mini App button to a 7-day public `g-` share stored in Redis.
- Excuses: curators exclude a student from lessons ("officially excused", from a date with an optional end, whole days, specific lessons or subjects); students request an excuse with a template (illness, volunteering, olympiad, family, other), dates, lessons, documents and a message thread; the curator approves or rejects from the web or Telegram. Excused lessons are locked in the journal, counted absent and excused, and get a work-off; the AI and MCP show them as officially excused.
- Face photos for entrance devices: students upload their own unless a curator or administrator has set one; administrators issue, revoke and audit entrance device keys (7-day call log); `POST /v1/device/identify` returns the student and the excuse status and tells the curator when a student who is not excused leaves during lessons. New dependency `opencv-python-headless` (YuNet and SFace models baked into the image).
- Personal API tokens (`ihsp_pat_`, scopes `me:read`/`me:write`, expiry, revocation, last use) for the `/v1/me/*` API.
- Administrators unseal Vault from the admin app (`/v1/admin/vault/*`, OTP step-up, the key share is never logged or stored).
- App map: `GET /v1/app-map` and a `find_feature` tool for the assistant and every MCP server; a four-step onboarding tour in the bot.
- Deployment: `scripts/deploy.sh` reads a git-ignored local env file and calls `scripts/cloud_deploy.sh`, which runs migrations, waits for a stability gate and rolls back to the previous image tag when the gate fails.
- Admin: `GET /v1/admin/users/{user_id}/face-photo` returns a student's face photo to administrators only.
- Dashboard: widgets `library_loans` and `notebook_recents`, and a full-width `4x1` size for announcements, alerts and today's lessons.

### Changed

- One rule for "excused" across the timetable, journal, attendance, dashboard and AI tools; schedule items carry `excused` and `excuse`.
- Bot: per-chat command menus, a hub menu, paginated lists and navigation footers.
- A sealed Vault is reported as sealed, so the admin app can offer the unseal page.
- README: a new banner and current screenshots.

### Fixed

- Gemini redirect sync received no query from nginx, so the `redirect_uri` error remained.

### Known issues

- Telegram widget method field names are not yet confirmed against the live Bot API; widgets stay off by default.
- Guest visualization links are public to anyone holding the link for 7 days.
- A sealed Vault is detected by matching the error text.
- A first deploy has no previous tag to roll back to.

## [1.1.1] - 2026-11-06

### Added

- First-time EMIS registration with a typed EMIS ID and a date of birth or unique password, limited to 5 wrong passwords per ID per hour.
- A required Telegram step in registration: a one-time `/start` link, or automatic linking inside the mini app.
- `POST /v1/id/me/emis-password/change`: change the password in EMIS with the current EMIS password and a second factor.

### Changed

- The public registration picker shows initials instead of given names.

### Fixed

- `/v1/admin/login-cues` and `/v1/admin/oauth-clients` answered 404 in production: nginx did not route them to the identity process.
- Gemini connectors failed with a `redirect_uri` error: per-user Google redirect URIs are now added to Gemini clients at authorization.

- `scripts/cloud_deploy.sh` could report success without restarting containers: `docker compose run` consumed the piped deploy script.

### Known issues

- The Telegram step is enforced in the web flow only; an account that leaves the page stays without a link.

## [1.1.0] - 2026-11-06

- Sharing: share a notebook or file by sign-in link or with named people, chat read-only in a private thread on your own limits, copy a shared notebook, attach one as live base materials.

### Changed

- **Breaking for MCP clients:** `get_marks` now returns marks grouped by subject (`{"subjects": [{"subject_id", "subject_name", "marks": [...]}]}`), for a date range or for exact semesters. A flat list of marks is gone, and a subject without marks has no entry.
- The MCP tool `get_course_media_link` now reports `idempotentHint: false`, because each call replaces the previous link.
- Bot menu buttons have icons, and their wording now matches the web apps: "Grades", "Email" and "Open the app" in English, "Уроки" in Russian.

### Added

- MCP lessons carry local start and end times, and `get_lesson_detail` returns material status and resources.
- MCP tools have no 200-card limit per call. A set still holds at most 500 cards.
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

- Lessons EMIS still lists are no longer shown as cancelled when a weekday has different lesson times; a day without its own time borrows the nearest one until Administration sets it.
- Injected instructions in tool output, search results and notebook passages are removed before the model sees them, and messages attacking the rules get a fixed refusal.
- Assistant answers keep only the result of a worked sum, unless the question asks how or why.
- A media link tied to a connector is refused if the process cannot check that connector. The check is now set up with the LMS rather than in a later step.
- A star stored on a multiple-choice certificate field is ignored, so it can no longer break the statistics.
- Gemini MCP: Gemini CLI loopback redirects can self-register, and pre-created Gemini clients list the fixed CLI redirects. Each deploy updates existing pre-created clients.
- The EMIS bell sync no longer removes a different Friday or brings back a block removed from one day.

### Known issues

- Friday lesson times have not been checked against real EMIS data. EMIS sends no weekday times, so Administration sets them. Lessons wrongly cancelled earlier may need restoring by hand.
- The student assistant sometimes answers a Russian question about marks in English.
- The injection filter uses patterns: it can remove harmless text and miss new attacks.
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
