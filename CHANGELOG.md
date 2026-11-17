# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/). Release tags are `vX.Y.Z`; images are published as `X.Y.Z`, `X.Y` and `sha-<commit>`.

## [Unreleased]

### Added

- Admission: `GET /v1/admission/consent/purposes` (localized titles and texts), `student_name` in the caseload rows and `stages` in the config.
- Admission notifications for staff comments, affordability sign-off requests and grants, and ready item reviews; app map entries for the chooser, documents, help, activities and setup pages.
- The `admission` Hydra client, the `admission.ihsu.uz` host in compose and nginx, and the `X-IHSP-App` CORS header.
- Admission workflow: journey path, preferences questionnaire, Discover matches with swipe decisions and undo, per-university chances (hidden unless `ESTIMATES_STUDENT_VISIBLE`), university logo and cover, documents checklist priorities, mentoring switches, and voice input behind the AI consent.
- Demo catalog: Wikimedia logos and covers, institution type and setting facts, and checklist priorities for the demo student.
- Admission refinement round: activity and honor categories with A–E grades and Common App limits, self-reported outcomes with deadline nudges, prep plans, a catalog of opportunities and scholarships (tuition, money, fellowships; local and international) with organization logos, comments and reports, a per-university AI chat with automatic research once per student and university (Exa results cached 14 days), supplemental essay prompts per institution and cycle, consultations in place of help requests, a staff-edited knowledge base, scoped MCP personal tokens, logo zoom and fit, and per-university academic and activity suggestions.

### Changed

- Admission: a binding round without an affordability sign-off answers `admission/affordability_gate`; proofs with several sources answer `admission/proof_source`; help notifications carry `request_id`.
- The AI consent purpose is version 2 (it now mentions audio); students re-consent once.
- Admission access: the outcomes summary shows hidden names only to admins and assigned staff, and audits each view; consultations are limited to admins and staff assigned to the student; supplemental prompts and logo edits need `catalog:curate`; MCP `read_document` needs the new `admission:documents` scope and the student's consent; erasing a student also clears authored KB articles and opportunities and revokes admission tokens (`opportunities.created_by` is nullable, migration `admission_0034`). `AdmissionActor.blocked` and the `blocked` ineligible reason are removed.
- Admission uni chats run on the fast tier, so automatic research no longer uses the weekly smart limit; deadline PATCH clears fields sent as null; deadline removal is one transaction; KB status filtering happens in SQL.

### Security

- The edge nginx runs 1.31.9, which fixes the ten vulnerabilities disclosed on 2026-11-18, among them the HTTP/2 remote code execution CVE-2026-123007 ("nginx2root"). The web image keeps `nginx-unprivileged` 1.31.7 until upstream publishes 1.31.9; it listens only on the internal network behind the edge nginx.
- Compose images: bugsink 2.6.3, python 3.13.18.

## [1.6.3] - 2026-11-16

### Added

- Telegram Guest Mode: the bot answers @mentions and replies in any chat through `answerGuestQuery`, with the public guest assistant only (needs `open_ai_agent` and Guest Mode in @BotFather). Quoted messages are treated as untrusted data, unknown links are dropped, and there are per-chat and global daily limits (`IHSP_TELEGRAM__GUEST_CHAT_*`).

### Changed

- The default dashboard keeps only what the shell does not already show: next lesson, upcoming controls, homework, new marks, flash cards due, alerts and announcements. Saved layouts are unchanged.
- Dependencies: aiobotocore 3.10, anthropic 2.3, fastapi 0.162, pydantic-settings 2.16, sentry-sdk 2.73, tzdata 2026.6, uuid-utils 1.2 and the dev tools; compose images mailpit 1.33, nginx 1.31, certbot 5.9; docker/login-action 4.7. taskiq stays below 0.13 (taskiq-redis 1.2.4 needs redis 8). Dependabot no longer proposes Python minor versions (the image and lock target 3.13).
- Code scanning receives only fixable CRITICAL and HIGH image findings; unfixed Debian findings (ffmpeg 7.1.5 and others) no longer open alerts.

### Fixed

- `/v1/public/client-config` answers CORS preflights from every app origin (it was share-only, so app boots failed with a CORS error).
- A face photo now becomes the user's profile photo, so avatars show it. A student's own upload keeps an admin-set photo, and removing the face removes its copy.
- Server-to-server migration restores everything: all three databases with their owners and passwords, Redis from its RDB (it was ignored under AOF), external and merged S3 buckets, and Vault with the old unseal keys. Runs hold a lock, `finish` refuses a second run, and `abort` knows whether the restore had started. Verified twice between two hosts with row, key and object counts identical.
- The Lint workflow passes again (a missing return annotation in the deploy tests).

## [1.6.2] - 2026-11-15

### Fixed

- Production treats an unset or empty `IHSP_TELEGRAM__BOT_TOKEN` as "use the default bot's Vault token" in every process; in 1.6.1 removing the line stopped all services (the empty value fell back to the dev token) and migrate, mail and scheduler needed the bot AppRole.
- `prod_init.sh vault` also revokes its short-lived Vault token when the run fails.

## [1.6.1] - 2026-11-15

### Changed

- `IHSP_TELEGRAM__BOT_TOKEN` is optional in production when `IHSP_BOT_VAULT__*` is set: login, mini-app sign-in, the bot and notifications then use the Vault token of the default bot. `python -m app import-default-bot` stores the env token in Vault once (idempotent, never prints it); the identity service now gets the `IHSP_BOT_VAULT__*` AppRole.

### Security

- `prod_init.sh vault` revokes every earlier AppRole secret id (identity, telegram-bots, backup) before issuing new ones, does its work with a 15 minute Vault token instead of the root token and revokes it at the end, and reminds the operator to move `secrets/vault-init.txt` off the server.

## [1.6.0] - 2026-11-15

### Added

- Legal consent is enforced on the server: until a signed-in user has accepted the current published documents, every authenticated HTTP route answers `403` `legal/acceptance-required`, MCP tools are refused and the Telegram bot replies with a link to accept. Open without consent: `/v1/legal/*`, `/v1/me/legal/*`, `GET /v1/id/me`, `/v1/id/me/sessions*`, `/v1/me/privacy/*`. The web apps show the consent gate on that error.
- Server-to-server migration: Admin > Server migration (`GET /v1/admin/migration`, `POST /v1/admin/migration/start|rollback`, admin, step-up, audited) queues a request for the root host runner `scripts/migrate_runner.sh` (systemd path unit `materials/systemd/ihsp-migration.*`); the target is prepared with `scripts/migrate_target.sh`. Maintenance mode answers writes with `503` `common/maintenance` and `GET /v1/public/maintenance` feeds the banner of every web app. New setting `IHSP_MIGRATION__DIR`.
- Telegram AI chat: one forum topic per AI chat in private chats (table `ai.telegram_topics`, rename sync, icon pick, `/delete` with confirmation); UI blocks come through the `show_ui_block` tool and are shown at the end of the answer message, after the text, with per-channel prompts.

- Langfuse tracing of model calls (`IHSP_LANGFUSE__PUBLIC_KEY`, `__SECRET_KEY`, `__HOST`, `__CAPTURE_CONTENT`): task, model, tokens, latency, hashed user id and chat/notebook session; content only when `CAPTURE_CONTENT=true`; off without keys, never blocks a request, flushed on shutdown.
- Legal documents module: administrators edit versioned privacy, terms, biometric and AI documents (uz, ru, en) and publish them; `GET /v1/legal/documents[/{kind}]`, `GET /v1/me/legal/pending`, `POST /v1/me/legal/accept`, `/v1/admin/legal/*`. Registration (`POST /v1/id/register/complete`) takes `accepted_legal` and answers `legal/consent-required` when a published document is not accepted.
- Privacy module: a ZIP export of the user's data (`POST`/`GET /v1/me/privacy/exports`, `GET .../{id}/download`, one per 24 hours, link valid 7 days) and administrator-reviewed account erasure (`GET`/`DELETE /v1/me/privacy/erasure`, `/v1/admin/privacy/erasure-requests[/{id}/approve|reject]`). A personal-data spec per module drives export and erasure; the `privacy.erase_owner` job runs after the retention window.
- Reading lists: librarians pin lists (`PUT /v1/library/reading-lists/{id}/pin`) and set their sequence (`PUT /v1/library/reading-lists/order`); everyone sees pinned lists first, then the manual order. New cards carry `pinned` and `sort_order`; migration `library_0004`.
- Several Telegram bots: a registry (`admin.telegram_bots`, migration `admin_0005`) with per-bot features (`ai_agent`, `open_ai_agent`, `commands`, `notifications`, `announcements`, `mini_app`); tokens live only in Vault (`IHSP_BOT_VAULT__*`, AppRole `telegram-bots`, one path per bot) and the API shows the last four characters. The env token is imported as the default bot, which keeps today's behaviour. Admin routes `GET`/`POST /v1/admin/bots`, `PATCH /v1/admin/bots/{bot_id}`, `POST /v1/admin/bots/{bot_id}/rotate-token`, `POST /v1/admin/bots/announcements` (audited; every write needs a step-up `otp_code`, a wrong code answers 403 `identity/step-up-invalid`; 503 `admin/bot-telegram-unavailable` when Telegram is unreachable). Each extra bot has its own webhook path `/telegram/b/{hmac}` and secret header. Feature switches apply within 30 seconds; adding, enabling or rotating a bot needs a bot process restart. Existing servers need the `telegram-bots` AppRole first: see "Upgrading an existing server" in `docs/telegram-bots.md`. `iht-web` needs `bun run sync:openapi`.
- LMS access rules per course and per lesson: audience `public`, `signed_in`, `students` or `chosen` (groups and users), and `hidden` or `locked` when denied (`GET`/`PUT /v1/lms/courses/{id}/access`, `PUT /v1/lms/courses/{id}/steps/{step_id}/access`, MCP tool `set_access` under `lms.courses.write`; migration `lms_0005_access_rules`). A locked lesson answers 403 `lms/content-locked` and cards and outlines carry `locked`/`access`; the course page gives the lead as a contact (no Telegram handle for guests). Progress and points count only lessons the viewer can see; an attempt started before a lock can still be saved and submitted. Guest routes under `/v1/lms/public` are limited to 120 requests per minute per address.
- MCP tools `get_my_group` (scope `group:read`), `get_rating_book` (new scope `rating_book:read`) for students and `list_notifications` (scope `notifications:read`) for students and teachers; scope release `2026-12-mcp-2`. The scheduler queues `identity.offer_mcp_scopes` on every start, so after an update users of earlier connectors are offered the new scopes at once (deduplicated per user and release); accepting widens the connector without a Hydra client change.
- Academic: administrators delete a group (migration `academic_0014`); a student's group can be unset (`profile.group` is `null`) and every reader handles it. My group shows classmates' photos unless a student opts out of photo sharing.
- ПК/ИК control periods in the timetable, subgroup filtering, and EMIS-like student screens (rating book, honours) backed by EMIS data; EMIS sign-in failures answer 409 instead of 401.
- Library: catalogue text search, reader markup, covers, and an administrator backfill button for book metadata.
- MCP history tools for chats (`list_chats`, `get_chat`, scope `chats:read`); quick AI questions from the assistant; a notice in the web chat when the conversation continues in Telegram; per-bot chat descriptions.
- Public LMS: guests browse and read public courses under `/v1/lms/public`; course outlines group lessons by section.
- Sitemaps and robots for the public apps. Administrators upload the lyceum logo (png, jpeg or webp, up to 1 MiB, stored in S3): `PUT`/`DELETE /v1/admin/settings/lyceum-logo`, public `GET /v1/public/lyceum-logo`, and `branding.lyceum_logo_url` in `GET /v1/public/client-config`.
- The data export asks for a step-up code; maintenance mode refuses writes everywhere, including background ones.
- The pre-migration dump of `scripts/cloud_deploy.sh` covers the main and Hydra databases and is encrypted with `age` to `BACKUP_AGE_RECIPIENT` (`backups/pre-<tag>-<stamp>.dump.age`); the deploy stops before migrating without a recipient unless `IHSP_DEPLOY_PLAIN_DUMP=1`. `scripts/restore.sh` restores it and a failed deploy prints the command.

### Changed

- The calendar hides other subgroup lessons by default: the `timetable:hide-other-subgroup` flag in `preferences.onboarding_dismissed` is replaced by `timetable:show-other-subgroup` (migration `identity_0015` drops the old flag).
- `DELETE /v1/id/me` answers 202 with `{request_id, status}`: it files an erasure request for administrator review instead of scheduling deletion at once. Signing in during the window restores the account and closes the request.

### Fixed

- Lesson generation no longer revives a cancelled lesson linked to EMIS; reviving it collided with the EMIS lesson on `ex_lessons_room_no_overlap` on every run.
- The production bot process gets the SMTP relay settings, so "Telegram linked" mail is sent instead of failing on `localhost:1025`.
- EMIS outages and missing files log at info or warning instead of error; a missing file is not downloaded again on every sync.
- Learner LMS responses are `Cache-Control: private, no-store`: a shared browser no longer shows another account's cached course or lesson.
- The production compose passes the Langfuse settings, `IHSP_LIMITS__AI_TEXT_MAX_BYTES` and the notebook web-material settings, which were documented but ignored; a test keeps `.env.prod.sample` and the compose in step.
- `alembic check` covers the `certificates` schema.
- `materials/.env.prod.sample` documents `IHSP_BOT_VAULT__ROLE_ID` and `IHSP_BOT_VAULT__SECRET_ID`.

## [1.5.1] - 2026-11-14

### Added

- Universal MCP server `app` (`/app`, audience `mcp-app`) for students, teachers and LMS users: the student, teacher and LMS tools in one connector, tool names prefixed by their source server (`student_`, `teacher_`, `lms_`) and scopes namespaced (`teacher:marks:write`). The tool list, consent screen and every call honour the roles of the source server. `GET /v1/id/mcp-scopes`, connectors and the `server` filter of the admin MCP activity accept `app`.

### Fixed

- A connector of the teacher MCP server could not be stored: migration `identity_0014` widens the `server` CHECK of `id.mcp_connectors` to student, lms, admin, teacher and app.

## [1.5.0] - 2026-11-14

### Changed

- `GET /v1/me/today` is faster: the student, the next study day, the homework and the lesson items are resolved once per request, and all teachers come from one identity lookup (response unchanged).

### Added

- `python -m app seed-review`: creates or resets the public test accounts of the ChatGPT app review (student, teacher and LMS) with made-up data (group, timetable, lessons, marks, attendance, homework, a quiz, flash cards and a published course); safe on production, reruns change nothing that is right. The reviewer guide is `docs/chatgpt-review.md`.
- Login cues kill switch `IHSP_FEATURES__LOGIN_CUES` (off by default: admin and public cue routes answer 404, the admin page leaves the app map), `POST /v1/admin/login-cues/bulk-delete`, and the public `GET /v1/public/client-config` (feature flags and `IHSP_DOCS__*` links).
- A group added without an EMIS id is adopted by a normalized name match (case, spaces, hyphens, Cyrillic look-alikes), and the first EMIS link of a group kicks the new task `academic.repull_group`: it forces the curriculum and a full timetable backfill and queues a sync for every other member with a working EMIS link. Later registrations do nothing extra.
- Step-up and other one-time codes: a failed Telegram send is retried once, falls back to the verified recovery email, and when nothing delivers the code and cooldown are dropped and the request answers 503 `id/otp-delivery-failed` instead of a silent 202.
- Documentation site (MkDocs Material, published to GitHub Pages by `.github/workflows/docs.yml`) with guides for personal tokens and entrance devices; the `docs` dependency group holds `mkdocs-material`.
- Planner: each target of `GET /v1/me/marks/subjects/{id}/planner` has `paths`, up to five minimal ways to reach it (`extra_lesson_fives`, lowest `midterm` and `final`).
- Student card: `GET /v1/me/student-card`, `POST /v1/me/student-card/tokens` (a two-minute token, only its SHA-256 is kept in Redis) and the public `GET /v1/public/student-cards/{token}` with `/photo` (404 `student_card_not_found`); `iht-web` needs `bun run sync:openapi`.
- Honours: `GET /v1/me/honours` (red diploma, gold and silver medal rules with the blocking marks), admin rules under `honours` of `PUT /v1/admin/settings`, `GET /v1/me/emis/rating-book` (the EMIS rating book link); the EMIS profile gains the institution name, school certificate serial and number, direction and speciality; `iht-web` needs `bun run sync:openapi`.
- CORS exposes the `Date` header so the share card counts down by server time.

### Security

- `opentelemetry-api` 1.45.2.

### Known issues

- The assistant `find_feature` still lists the login cues page when cues are switched off.
- `seed-review` has no ПК/ИК period marks or notebooks; the admin MCP server has no review account.

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
