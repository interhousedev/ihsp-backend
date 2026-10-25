"""Files "used by": links, lesson resources and AI chats found through real SQL."""

from app.bootstrap.adapters.usage_resolver import UsageResolverAdapter
from app.modules.ai.infrastructure.orm.chat import Chat as ChatRow
from app.modules.links.domain.link import LessonRole, Link, LinkKind
from app.shared.ids import new_id
from tests.integration.conftest import ContainerFactory

from sqlalchemy import text


async def test_file_is_reported_where_it_is_linked_attached_and_discussed(
    make_container: ContainerFactory,
) -> None:
    """FILE-7: deleting a file warns about its short link, lesson and chat."""
    container = await make_container("all")
    owner, file_id, other_file = new_id(), new_id(), new_id()
    lesson_id, chat_id = new_id(), new_id()
    now = container.clock.now()
    links_uow = container.links.create_link.uow_factory  # type: ignore[attr-defined]
    async with links_uow() as uow:
        await uow.links.add(
            Link(
                id=new_id(),
                slug="doc1",
                kind=LinkKind.FILE,
                owner_id=owner,
                created_at=now,
                file_id=file_id,
                title="Syllabus",
            )
        )
        await uow.links.add(
            Link(
                id=new_id(),
                slug="les1",
                kind=LinkKind.FILE,
                owner_id=owner,
                created_at=now,
                file_id=file_id,
                lesson_id=lesson_id,
                lesson_role=LessonRole.MATERIAL,
                title="Slides",
            )
        )
        await uow.commit()
    async with container.sessionmaker() as session, session.begin():
        session.add(
            ChatRow(
                id=chat_id,
                owner_id=owner,
                assistant="student",
                title="Homework help",
                model="fake",
            )
        )
        await session.flush()
        await session.execute(
            text(
                "INSERT INTO ai.chat_messages (id, chat_id, seq, role, content, "
                "file_ids) VALUES (:id, :chat, 1, 'user', '{}', :files)"
            ),
            {"id": new_id(), "chat": chat_id, "files": [file_id]},
        )

    usage = UsageResolverAdapter(
        container.links.public,  # type: ignore[arg-type]
        container.ai.public,  # type: ignore[arg-type]
    )
    found = await usage.used_by([file_id, other_file])

    assert other_file not in found
    assert {(item.kind, item.label) for item in found[file_id]} == {
        ("link", "Syllabus"),
        ("lesson", "Slides"),
        ("chat", "Homework help"),
    }
