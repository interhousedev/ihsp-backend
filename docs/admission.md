# Admission

The admission app (`admission.ihsu.uz`) helps students prepare university applications. This page is for operators and staff. The full contract of every route is `openapi/openapi.json`.

## Who uses what

| Role | What they do |
|---|---|
| Student | Career and study field, activities and honors, universities and budget, essays, documents and deadlines, results. |
| Staff (counselors and other admission staff) | Caseload, consultations, the knowledge base, the university catalog, exemplars, the prompt studio. What each person may do follows their permissions (for example `catalog:curate` for catalog edits). |
| Administrator | Everything above, plus the AI limits and the users page. |

The student app has five sections: Career & study, Activities & honors, Universities & budget, Essays, Documents & applying. Home gives an overview, and the knowledge base, consultations and settings sit in the footer links. Old routes redirect to the new places.

## Essay reviews

- One base review per essay text and locale, plus one review per chosen university (at most 5 universities per request). A review needs at least 50 words.
- Weekly limits per student: `IHSP_LIMITS__ADMIT_ESSAY_REVIEW_PER_WEEK` (10) for base reviews and `IHSP_LIMITS__ADMIT_ESSAY_UNI_REVIEW_PER_WEEK` (30) for university reviews. `-1` removes a cap.
- Administrators change them at runtime on the admin "Limits & usage" page, group "Essay reviewer". The same group holds `admit_essay_studio_runs_per_day` (30), the prompt studio runs per staff member and day; staff are not unlimited there.
- The quality and fairness of the reviewer can be measured with `scripts/admission_essay_bench.py`.

## Essay encryption and Vault

Essay text (drafts, versions, ideas, comments, reviews) is encrypted per student before it reaches the database.

- AES-256-GCM with a random key per student, kept in Vault KV v2 (`IHSP_ESSAY_VAULT__KV_MOUNT`, default `secret`, under `IHSP_ESSAY_VAULT__KV_PREFIX`, default `admission-essays`, one path per student).
- The owner, record and column are bound as associated data, so a blob copied to another row, column or student does not open.
- Processes cache keys for up to 5 minutes (1024 keys).
- Production needs the `admission-essays` AppRole: `IHSP_ESSAY_VAULT__ROLE_ID` and `IHSP_ESSAY_VAULT__SECRET_ID`. `scripts/prod_init.sh vault` creates it and writes both to `.env.prod`. Without them essays fail closed with HTTP 503 instead of storing plaintext. The identity AppRole is never used for essays.
- Erasing a student destroys the key, so remaining blobs cannot be read. After erasure, a process may still use a cached key for up to 5 minutes.
- Back up Vault with the other data: an essay without its key is lost.
- The dev Vault in `materials/docker-compose.dev.yaml` runs in memory, so its keys are gone after a restart. Essays of such a student answer 503 `admission/essay_key_unavailable` until the demo data is re-seeded; a new essay still works.
- Essay routes return 503 `admission/essay_key_unavailable` when a student's key is missing. Nothing is stored in plaintext.

## Sharing an essay for review

A student can create a review link for an essay (1 to 90 days, 30 by default, at most 20 active links per essay). The token sits in the URL fragment, so it is not sent to servers in the request line, and only its SHA-256 hash is stored. A link can allow comments and can be revoked at once. Guests open the reviewer page of the share app, comment on spans of text and are limited to 20 comments per link and hour and 60 opens per address and hour. A guest sees only that essay. Public routes are under `/v1/public/admission/essay-review`.

## Exemplars

Exemplars are admitted essays that counselors add or import (up to 50 per import) with a title, prompt, tags and a source link. Students see excerpts (about 80 words) with the link, never the whole text, and the AI compares a student's essay with matching exemplars. Staff manage them under Exemplars in the staff navigation (`/v1/admission/staff/exemplars`).

## Prompt studio

Staff edit the four reviewer prompt slots: `base`, `uni`, `check` and `feedback`. The studio validates a prompt (it blocks an empty, too long or malformed prompt or an unknown placeholder and warns when it does not name the biases to avoid), runs tests on up to 3 samples, publishes a version and reverts to an earlier one. Routes: `/v1/admission/staff/prompt-studio/slots`.

## The `admission:catalog` token for AI agents

Catalog maintenance can be handed to an AI agent that researches universities and proposes them; a person always approves. Create the token as described in [Personal tokens](personal-tokens.md): only non-student staff may, with a one-time code, `admission:catalog` as the sole scope and at most 90 days. MCP servers refuse it.

The token reaches only these routes (`_CATALOG_ALLOWLIST` in `app/interfaces/http/dependencies.py`):

| Method | Route |
|---|---|
| GET | `/v1/admission/catalog/institutions`, `…/institutions/{id}`, `…/institutions/{id}/supp-prompts`, `…/scholarships`, `…/facets`, `…/study-fields` |
| GET | `/v1/admission/staff/catalog/institutions/{id}`, `…/fact-spec` |
| GET, POST | `/v1/admission/staff/catalog/proposals` |
| POST | `/v1/admission/staff/exemplars`, `/v1/admission/staff/exemplars/import` |

An agent reads `fact-spec` for the typed facts, looks at what the catalog already has, researches the official sources and posts a proposal with a cited `source_url` and year for every fact. Proposals are rate limited by `IHSP_ADMISSION__CATALOG_PROPOSALS_PER_DAY`, cannot be approved by the token, and take effect only after a human review. The token cannot read any student data. Exemplar creation is also open to it, so keep it for trusted agents.

## Profile photos

Every role can set its own photo with `PUT /v1/me/photo` and remove it with `DELETE /v1/me/photo`. After an upgrade run `python -m app backfill-profile-photos` once to create photos from enrolled faces.
