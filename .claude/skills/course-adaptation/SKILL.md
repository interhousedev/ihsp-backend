---
name: course-adaptation
description: Use for translating or adapting open courses (OpenStax, CS50, other CC material) into uz/ru LMS courses; licences, attribution, glossary, review gates; not for original lessons
---

# Course adaptation

## Licences (check the book's own page every time)

- **OpenStax**: the whole library is now **CC BY-NC-SA 4.0** (https://openstax.org/blog/openstax-licensing, https://help.openstax.org/s/article/Licensing-information-of-OpenStax-textbooks). Earlier CC BY editions are not a safe assumption; use the licence printed in the edition you copy.
- **CS50** (Harvard): CC BY-NC-SA 4.0 (https://cs50.harvard.edu/x/license). Code samples and course names are attribution material; "CS50" is a Harvard mark, so call ours "adapted from CS50", never "CS50".
- NC: the lyceum's free courses are fine; never put adapted material behind payment or ads.
- SA: the adaptation (text, tests, flashcards, video) is published under CC BY-NC-SA 4.0 too.
- Third-party images inside a book can have their own licence: check each figure's credit line; replace if unclear.

## Attribution (put it in the first text block of the course and in the library record)

> Адаптировано из: OpenStax, *Biology 2e*, Rice University, https://openstax.org/details/books/biology-2e, CC BY-NC-SA 4.0. Изменения: перевод на русский, сокращение, новые примеры, тесты и карточки. Адаптация распространяется на тех же условиях.

Give the same in uz and en. Do not imply endorsement by OpenStax or Harvard.

## Pipeline per book or course

1. Source: download the CNXML/HTML (OpenStax GitHub `openstax/osbooks-*`) or CS50 notes; keep section IDs.
2. Glossary first: extract terms, translate with a subject teacher, freeze it (CSV per subject, uz/ru/en).
3. Machine translation per section (AI task with the glossary in the prompt; skill://prompts, skill://ai-studio-quality), Markdown and LaTeX preserved.
4. Automatic QA: terms match the glossary, numbers and formulas unchanged, no untranslated English, uz uses ʼ (U+02BC).
5. Localise examples (UZS, Tashkent, Uzbek law only after a lawyer or teacher checked it).
6. Build blocks: summary text, video (skill://edu-video), test 8–10 mixed questions, flashcards 10–15, a practice task.
7. Human gates: subject teacher (accuracy), language editor (uz/ru), head of department (publish). Publish via skill://lms-publish.

## Learning design for 15–18 year olds

- Retrieval practice and spacing (Dunlosky et al. 2013, https://doi.org/10.1177/1529100612453266): a test after each lesson, flashcards for spaced review.
- Short videos, ≤ 6 minutes (Guo, Kim & Rubin 2014, https://doi.org/10.1145/2556325.2566239).
- Mayer's multimedia principles (https://doi.org/10.1111/jcal.12197): segmenting, signalling, coherence, pretraining (key terms before the video).
- Worked example first, then a practice task; one idea per step.
