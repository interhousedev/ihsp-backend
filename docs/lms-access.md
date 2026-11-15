# LMS access rules

A course and each of its lessons (steps) can carry an access rule. Course editors with the `lms_admin` role or the `manage_staff` permission set them on the **Access** tab of a course in the LMS app, on the lock button of a lesson in the outline editor, or through the MCP tool `set_access`.

## Rule

| Field | Values |
|---|---|
| `audience` | `public` (anyone, guests included), `signed_in`, `students`, `chosen` |
| `group_ids`, `user_ids` | for `chosen`: up to 500 groups and 500 users |
| `when_denied` | `hidden` (default): the course or lesson is not shown; `locked`: it is listed with a lock and its content is withheld |

A lesson rule applies on top of the course rule. Course staff always see everything.

## Routes

| Route | Purpose |
|---|---|
| `GET /v1/lms/courses/{course_id}/access` | the course rule and every lesson rule |
| `PUT /v1/lms/courses/{course_id}/access` | set the course rule (`AccessRuleBody`) |
| `PUT /v1/lms/courses/{course_id}/steps/{step_id}/access` | set a lesson rule |

## Effects

- Progress, step counts and points count only the lessons a learner can see.
- Saving or submitting an answer to a lesson the learner cannot open is refused.
- Publishing a version drops the rules of lessons that no longer exist.
- Guests read public courses through `/v1/lms/public`, limited to 120 requests per minute per address (HTTP 429 above that). A lesson outside its enrolment window answers 404.
- A changed rule updates a learner's stored progress percentage at the next publish or progress refresh.
