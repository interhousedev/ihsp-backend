# LMS publish API

An agent publishes with the scopes a person already has, through the MCP server `lms` and the files API.

1. Upload each lesson video: `POST /v1/files` with purpose `lms_video` (up to 500 MB), `PUT` the bytes to the presigned URL, then `POST /v1/files/{file_id}/complete`.
2. `create_course` (scope `lms.courses.write`).
3. `build_course` (scope `lms.modules.write`): sections, steps and blocks in one call. A `video_file` block needs a ready `lms_video` file.
4. Fix with `update_step` and `update_block`.
5. Publish: `POST /v1/lms/courses/{course_id}/publish`; `GET /v1/lms/courses/{course_id}/pending` lists unpublished changes. Students see only published versions.

Library books are published by a librarian: `POST /v1/manage/library/books/{id}/publish`.
