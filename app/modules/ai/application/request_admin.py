"""Administrators' read view of the published AI request registry."""

from collections.abc import Callable

from app.modules.ai.application.publish_requests import PublishUnitOfWork
from app.modules.ai.domain.prompt_registry import ALL_LOCALES, BUILT_IN_VERSION
from app.modules.ai.domain.requests import AiRequestInfo, AiRequestNotFoundError
from app.modules.ai.ports.requests import RequestRecord
from app.shared.actor import Actor


class RequestAdmin:
    """Lists the requests the code published, with the state of their templates."""

    def __init__(self, uow_factory: Callable[[], PublishUnitOfWork]) -> None:
        """Keep the transaction factory."""
        self.uow_factory = uow_factory

    async def list(
        self,
        actor: Actor,
        *,
        owner_app: str | None = None,
        pipeline: str | None = None,
        include_retired: bool = False,
    ) -> list[AiRequestInfo]:
        """The registered requests, filtered; retired ones only when asked."""
        async with self.uow_factory() as uow:
            records = await uow.requests.list(
                owner_app=owner_app, pipeline=pipeline, include_retired=include_retired
            )
            return [await self._info(uow, record) for record in records]

    async def get(self, actor: Actor, request_id: str) -> AiRequestInfo:
        """One registered request, retired or not."""
        async with self.uow_factory() as uow:
            record = await uow.requests.get(request_id)
            if record is None:
                raise AiRequestNotFoundError(support_details=request_id)
            return await self._info(uow, record)

    async def _info(
        self, uow: PublishUnitOfWork, record: RequestRecord
    ) -> AiRequestInfo:
        task, _, name = record.template_id.partition("/")
        active = next(
            (
                v
                for v in await uow.prompts.active(task)
                if v.name == name and v.locale == ALL_LOCALES
            ),
            None,
        )
        active_version = active.version if active else BUILT_IN_VERSION
        changed = (
            active is not None
            and active.source == "admin"
            and record.code_version > active.version
        )
        return AiRequestInfo(
            id=record.id,
            owner_app=record.owner_app,
            task=record.task,
            pipeline=record.pipeline,
            template_id=record.template_id,
            args_schema=record.args_schema,
            tools=record.tools,
            summary=record.summary,
            published_at=record.published_at,
            retired=record.retired,
            active_version=active_version,
            code_version=record.code_version,
            code_changed_since_active=changed,
        )
