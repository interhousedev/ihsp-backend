"""The one excused rule in SQL, for the aggregate attendance reports.

It mirrors ``effective_excuses``: an absent student is excused when an excuse mark
is saved for the lesson or an approved excuse covers its date and, when it names
lessons or subjects, the lesson or subject (``Excuse.covers``). Callers combine
it with their own "absent" test.
"""


def excused_sql(lesson: str, student: str) -> str:
    """Return a boolean SQL expression: ``student`` is excused for ``lesson``.

    ``lesson`` is the alias of ``academic.lessons`` and ``student`` a SQL
    expression of type ``uuid``; both come from code, never from input.
    """
    return f"""(
  jsonb_exists({lesson}.attendance_excused, CAST({student} AS text))
  OR EXISTS (
    SELECT 1 FROM academic.excuses x
    WHERE x.student_id = {student} AND x.status = 'approved'
      AND x.starts_on <= {lesson}.date
      AND (x.ends_on IS NULL OR x.ends_on >= {lesson}.date)
      AND (
        (COALESCE(cardinality(x.lesson_ids), 0) = 0
          AND COALESCE(cardinality(x.subject_ids), 0) = 0)
        OR {lesson}.id = ANY(x.lesson_ids)
        OR {lesson}.subject_id = ANY(x.subject_ids)
      )
  )
)"""
