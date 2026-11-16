---
name: admission
description: Use for app/modules/admission and /v1/admission routes: access policy, contexts, settings, consents, catalog data; not for other modules.
---

# Admission module

University-application workspace for students, counselors, mentors and transcript officers.

## Layout

- `app/modules/admission/{domain,ports,application,infrastructure,wiring.py}` as every module; ORM in `infrastructure/orm/` (schema `admission`, migration branch `migrations/versions/admission`). Never read another module's tables: use ports (`ports/consent.py`, `ports/courses.py`) fed by `app/bootstrap`.
- Routes: `app/interfaces/http/v1/admission/`; one file per slice, `routes_<slice>.py` (chooser, guest, help, profile, proofs, staff) included by `router.py`; schemas in `schemas.py` / `schemas_staff.py`; dependencies in `deps.py`. A new slice gets its own `routes_<slice>.py`, never grows `router.py`.
- Contexts: `AdmissionCtx` (the student or an allowed actor) and `HelperCtx` (counselor/mentor/transcript officer) from `deps.py`; handlers take them as parameters and pass the context to the use case, never read the user from the request.

## Access

- Every read and write of a student's data goes through `AccessPolicy` (`application/access.py`): it resolves the actor's entitlement and staff scope, checks `Permission` (`domain/permissions.py`), requires the student's **purpose consents** (`PurposeConsents`) and writes an audit event (`student.viewed` and others). Staff routes without it are a bug; a missing consent or scope answers like not found (no existence leak).
- Roles: counselor, mentor, transcript_officer are admission sub-roles; add a role only with its `Permission` set and tests of each refusal.

## Runtime settings

Admin-editable values live in `admission.runtime_settings` (`domain/runtime_settings.py`, `KNOWN_KEYS`). Missing keys fall back to the environment (`IHSP_ADMISSION__*`). A new key: add it to `KNOWN_KEYS`, a typed accessor, the admin route validation and tests; never read the table elsewhere.

## Private AI content

Admission prompts and answers (essays, grades, wellbeing) are private: their AI tasks (`ADMIT_*` in `app/shared/ai_tasks.py`) set `private_content=True`, so tracing and the ledger never store the text. Resolve prompts through the registry (skill `prompts`). Wellbeing questions are shown only when the runtime flag is on.

## Catalog data

`scripts/admission_import_catalog.py` and `infrastructure/catalog_data/` hold universities and programs. Only facts cited from an official source (the school, Scorecard, IPEDS) with source and year; where there is no cited official fact the field is `null`, never a guess, an estimate from memory or a model answer. Estimates (`domain/estimates.py`) are labelled as estimates and hidden from students unless `estimates_student_visible`.

## Checks

New tables or columns: `scripts/check_migrations.sh` (skill `migrations`). New routes: export OpenAPI (skill `api-contract`) and add the page to `app/shared/app_map.py`. Tests use fakes in `tests/fakes/admission/`.
