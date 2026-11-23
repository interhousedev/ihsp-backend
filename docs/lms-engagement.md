# LMS engagement

Daily review, streaks, mastery, class quests and nudges. All routes are under `/v1/lms`.

| Route | Purpose |
|---|---|
| `GET /engagement/summary` | XP, level, streak and what is due today |
| `GET /engagement/xp` | XP history; XP and levels are shared by every skin |
| `GET /engagement/review` | today's FSRS review queue |
| `POST /engagement/review/{item_id}/answer` | submit an answer for a review item |
| `POST /engagement/review/{item_id}/grade` | grade a review item (FSRS rating) |
| `GET /engagement/courses/{course_id}/mastery` | mastery map of a course |
| `GET /engagement/quests` | the learner's class quests |
| `GET`, `PUT /courses/{course_id}/engagement-settings` | per-course engagement settings (staff) |
| `GET`, `POST /courses/{course_id}/quests` | list and create class quests (staff) |
| `PATCH`, `DELETE /courses/{course_id}/quests/{quest_id}` | update or delete a quest (staff) |

Telegram nudges remind learners of due reviews and broken streaks; they use the notify module (`notify_0022`).

## Skins

The Playful (Duolingo-style) skin is offered on the first visit and can be changed in settings. XP and levels are the same in every skin.

The exact shapes are in `openapi/openapi.json`.
