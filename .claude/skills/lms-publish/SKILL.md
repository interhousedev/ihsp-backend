---
name: lms-publish
description: Use when an agent creates or publishes an LMS course from a manifest, uploads lesson videos, or publishes a library book; not for LMS UI or AI lesson generation
---

# LMS publish

An agent publishes with the scopes a person already has. Never add scopes, bypass consent or call internal use cases directly.

## Course from a manifest (MCP server `lms`)

1. Upload each video over HTTP (MCP `upload_file` is base64 ≤ 5 MiB and has no `lms_video` purpose):
   - `POST /v1/files` `{name, size, content_type:"video/mp4", sha256_b64, purpose:"lms_video"}` (≤ 500 MB) → presigned `PUT` the bytes → `POST /v1/files/{file_id}/complete`.
2. `create_course` (scope `lms.courses.write`), or reuse a course the connector is limited to (`course:<id>`).
3. `build_course` (scope `lms.modules.write`): sections → steps → blocks in one call. Block types:
   - `text` `{markdown}`; `video` `{url, caption}` (a link); `video_file` `{file_id, caption}` (an uploaded `lms_video`);
   - `test` with questions; `flashcards` with cards.
   - A `video_file` whose file is not an `lms_video`, or is not ready, is refused (`ContentInvalidError`).
4. Optional fixes: `update_step`, `update_block` (same block types), `add_*_block`.
5. `publish` with a short note. Students see only published versions.

`video_file` exists only in `AuthorBlockInput` (`app/shared/contracts/lms_blocks.py`). Model output schemas (`BlockInput`, `StepDraftInput`) must never offer it: a model cannot invent file IDs. The test `test_model_output_schemas_never_offer_an_uploaded_video` enforces this.

Captions: the video block has no caption-track field yet. Burn captions into the MP4 and put the VTT text and the transcript into a `text` block next to the video.

## Library book (HTTP, librarian token)

1. Upload: `POST /v1/files` purpose `library_book` (cover: `library_cover`) → PUT → complete.
2. `POST /v1/manage/library/books` (`BookInputBody`): title, authors, language, licence, subjects.
3. `POST /v1/manage/library/books/{id}/files` `{file_id, format, is_primary:true}`.
4. `POST /v1/manage/library/books/{id}/publish`. Bulk: `POST /v1/manage/library/import` `{csv_file_id}`.

Always fill the licence and the attribution of open material (see skill://course-adaptation).

## Checks

- `uv run pytest tests/lms/test_lms_blocks_contract.py tests/mcp/test_lms_ops_tools.py -q`
- Real DB: `IHSP_ENV_FILE=materials/dev.env uv run pytest tests/lms/authoring/integration/test_build_course_video.py -q`
- A new block type or field changes MCP schemas only; an HTTP change needs skill://api-contract.
