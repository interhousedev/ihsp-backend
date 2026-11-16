"""SQL storage of the assistant's threads and messages; always per student."""

from uuid import UUID

from app.modules.admission.domain.assistant import Action, Citation, Message, Thread
from app.modules.admission.infrastructure.orm.assistant import (
    AssistantMessageRow,
    AssistantThreadRow,
)

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _thread(row: AssistantThreadRow) -> Thread:
    return Thread(row.id, row.student_id, row.title, row.created_at, row.updated_at)


def _message(row: AssistantMessageRow) -> Message:
    return Message(
        id=row.id,
        thread_id=row.thread_id,
        role=row.role,  # type: ignore[arg-type]
        text=row.text,
        created_at=row.created_at,
        citations=[Citation(**c) for c in row.citations or []],
        actions=[Action(**a) for a in row.actions or []],
    )


def _action(a: Action) -> dict[str, object]:
    return {
        "kind": a.kind,
        "label": a.label,
        "url_path": a.url_path,
        "task": a.task,
    }


class SqlAssistantRepository:
    """Each call opens and commits its own session."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def create_thread(self, thread: Thread) -> None:
        """Store a new thread."""
        async with self._sm() as session, session.begin():
            session.add(
                AssistantThreadRow(
                    id=thread.id,
                    student_id=thread.student_id,
                    title=thread.title,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                )
            )

    async def get_thread(self, student_id: UUID, thread_id: UUID) -> Thread | None:
        """The student's thread, or None."""
        async with self._sm() as session:
            row = await session.scalar(
                select(AssistantThreadRow).where(
                    AssistantThreadRow.id == thread_id,
                    AssistantThreadRow.student_id == student_id,
                )
            )
            return _thread(row) if row else None

    async def list_threads(self, student_id: UUID, limit: int) -> list[Thread]:
        """The student's threads, latest first."""
        async with self._sm() as session:
            rows = await session.scalars(
                select(AssistantThreadRow)
                .where(AssistantThreadRow.student_id == student_id)
                .order_by(AssistantThreadRow.updated_at.desc())
                .limit(limit)
            )
            return [_thread(r) for r in rows]

    async def messages(self, student_id: UUID, thread_id: UUID) -> list[Message]:
        """The messages of the student's thread, oldest first."""
        async with self._sm() as session:
            rows = await session.scalars(
                select(AssistantMessageRow)
                .where(
                    AssistantMessageRow.thread_id == thread_id,
                    AssistantMessageRow.student_id == student_id,
                )
                .order_by(AssistantMessageRow.created_at, AssistantMessageRow.id)
            )
            return [_message(r) for r in rows]

    async def append(self, student_id: UUID, messages: list[Message]) -> None:
        """Store messages and touch the thread."""
        if not messages:
            return
        async with self._sm() as session, session.begin():
            for m in messages:
                session.add(
                    AssistantMessageRow(
                        id=m.id,
                        thread_id=m.thread_id,
                        student_id=student_id,
                        role=m.role,
                        text=m.text,
                        citations=[vars_of(c) for c in m.citations],
                        actions=[_action(a) for a in m.actions],
                        created_at=m.created_at,
                    )
                )
            await session.execute(
                update(AssistantThreadRow)
                .where(
                    AssistantThreadRow.id == messages[-1].thread_id,
                    AssistantThreadRow.student_id == student_id,
                )
                .values(updated_at=messages[-1].created_at)
            )

    async def delete_thread(self, student_id: UUID, thread_id: UUID) -> bool:
        """Delete the student's thread (messages cascade); False when absent."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                delete(AssistantThreadRow).where(
                    AssistantThreadRow.id == thread_id,
                    AssistantThreadRow.student_id == student_id,
                )
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    async def erase(self, student_id: UUID) -> tuple[int, int]:
        """Delete everything of the student; returns (threads, messages)."""
        async with self._sm() as session, session.begin():
            msgs = await session.execute(
                delete(AssistantMessageRow).where(
                    AssistantMessageRow.student_id == student_id
                )
            )
            threads = await session.execute(
                delete(AssistantThreadRow).where(
                    AssistantThreadRow.student_id == student_id
                )
            )
            return (
                int(threads.rowcount),  # type: ignore[attr-defined]
                int(msgs.rowcount),  # type: ignore[attr-defined]
            )


def vars_of(c: Citation) -> dict[str, str]:
    """A citation as a JSON object."""
    return {"source": c.source, "title": c.title, "url_path": c.url_path}
