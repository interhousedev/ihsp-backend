# LMS lesson blocks

Lessons are built from blocks. Besides text, video, tests and flashcards, a lesson can hold the blocks below. Authors add them in the lesson editor of the LMS app; agents add them through the MCP server `lms` (see [LMS publish API](lms-publish.md)).

| Block | What it does |
|---|---|
| Bluebook exam | A SAT or AP practice exam inside the lesson. |
| Code execution | Learners write and run code in a sandbox. The last submitted code is not restored when the lesson is reopened. |
| Custom HTML widget | An author-supplied interactive widget. The widget SDK reports a score; the block has a pass mark. |
| AI Review | A learner submits work and an AI session reviews it with feedback. |
| Video captions | A video block can carry caption tracks (VTT). |
| Tutor and micro-checks | A tutor answers questions about the lesson; interactive videos stop for short checks. With the tutor off the console logs a harmless 403. |

## AI Review routes

Sessions are created per block: `POST /v1/lms/steps/{step_id}/blocks/{block_id}/ai-review/sessions`. A session is read at `/v1/lms/ai-review/sessions/{session_id}`. Work is submitted with `POST /v1/lms/courses/{course_id}/steps/{step_id}/blocks/{block_id}/ai-review/submissions`. Model calls are named AI tasks and count against the usual AI limits.

## Course page

`GET /v1/lms/courses/{slug}/landing` returns the public course info page (see also `GET /v1/lms/courses/{slug}`). Legacy links of the form `/course/step/?course=<slug>` are not resolved and answer 422.

The exact request and response shapes are in `openapi/openapi.json`.
