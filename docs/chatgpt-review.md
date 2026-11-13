# ChatGPT app review

Public test accounts for the review of the IHT ChatGPT app. They hold made-up data only: no real student, teacher or EMIS record is behind them, and the passwords are public on purpose.

## Servers

Each server is a separate connector. Add the URL, then sign in.

| Server | URL | Account |
| --- | --- | --- |
| Student | `https://mcp.ihsu.uz/student` | `review.student` |
| Teacher | `https://mcp.ihsu.uz/teacher` | `review.teacher` |
| LMS | `https://mcp.ihsu.uz/lms` | `review.lms` |

The administration server (`https://mcp.ihsu.uz/admin`) is not part of this submission. It needs an administrator and a one-time code (step-up), so there is no public account for it.

## Accounts

| Login | Password | Roles | Covers |
| --- | --- | --- | --- |
| `review.student` | `IhtReviewStudent-2026` | student | student server |
| `review.teacher` | `IhtReviewTeacher-2026` | teacher | teacher server |
| `review.lms` | `IhtReviewLms-2026` | LMS creator, teacher | LMS server |

Each account only works with the server above; another server answers that the role may not use it. The accounts have no one-time code and no email.

## Sign-in flow

1. In ChatGPT, add the connector with the server URL.
2. ChatGPT opens the IHT ID sign-in page (OAuth with PKCE).
3. Enter the login and the password of the account for that server.
4. The consent screen lists the scopes the app asks for. Keep the defaults and accept.
5. ChatGPT returns to the chat and the tools are available.

A person can take scopes back at any time on the connectors page of IHT ID.

## Data

- **Student** (`review.student`): the "Review group" with a timetable for Monday to Friday (three lessons a day: Mathematics, English, Physics), lessons of the last four weeks and the next two, lesson marks on the past lessons, one absence, homework on the next two lessons, one upcoming quiz, a flash card set "Review: derivatives" and enrolment in the course "Review course: Derivatives" with its first step opened.
- **Teacher** (`review.teacher`): teaches all lessons of the Review group, with the roster, the journal, the attendance of the last lessons and the homework above.
- **LMS** (`review.lms`): author of the published course "Review course: Derivatives" (a text step, a test and a flash card step), with one enrolled student.

## Sample prompts

Student server:

- "What is my schedule for tomorrow?"
- "Show my marks in Mathematics."
- "What homework do I have?"
- "Create a flash card set with three cards about gravity."

Teacher server:

- "Show my lessons today."
- "Who was absent in my latest lesson?"
- "Set the homework for my next English lesson: read page 10."
- "List the upcoming assessments of my groups."

LMS server:

- "List my courses."
- "Show the structure of Review course: Derivatives."
- "Add a text step called Summary to the course."
- "Who is enrolled in the course and how far did they get?"

## Reset

The accounts are created, and put back to the state above, by `python -m app seed-review`. It is safe to run on production and can be run again at any time.
