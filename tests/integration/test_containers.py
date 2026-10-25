"""Every process builds its container over fakes; the module fields match its plan."""

from app.bootstrap.adapters.usage_resolver import UsageResolverAdapter
from app.bootstrap.common import PLANS
from app.shared.ids import new_id
from tests.integration.conftest import ContainerFactory

import pytest

HTTP_AND_WORKER = ("all", "api", "identity", "bot", "mail", "worker")


@pytest.mark.parametrize("process", HTTP_AND_WORKER)
async def test_container_builds_for_every_process(
    make_container: ContainerFactory, process: str
) -> None:
    """The process gets exactly the modules its plan names."""
    plan = PLANS[process]

    container = await make_container(process)

    assert container.identity.directory is not None
    assert container.academic.schedule.queries is not None
    assert (container.files is not None) is plan.files
    assert (container.mail is not None) is plan.mail
    assert (container.links is not None) is plan.full
    assert (container.academic.marks is not None) is plan.full
    assert (container.notify is not None) is plan.full
    assert (container.lms is not None) is plan.lms
    assert (container.notebooks is not None) is plan.full
    assert (container.identity.emis_services is not None) is plan.emis


async def test_all_has_every_module(make_container: ContainerFactory) -> None:
    """`all` wires the cross-module cycles: links, AI, flash cards, files usage."""
    container = await make_container("all")
    some_id = new_id()

    assert container.admin_tools is not None
    # The lazy proxies are bound: calls go through to real queries instead of raising.
    assert await container.ai.public.pending_approvals(some_id) == 0
    assert await container.links.public.is_shared(some_id) is False
    usage = UsageResolverAdapter(
        container.links.public,  # type: ignore[arg-type]
        container.ai.public,  # type: ignore[arg-type]
    )
    assert await usage.used_by([some_id]) == {}
    # The assistant reaches notebooks through the late bindings.
    assert container.ai.bindings.notebooks is container.notebooks.public
    assert container.ai.bindings.notebooks_commands is container.notebooks.commands
    assert await container.notebooks.public.used_by_files([some_id]) == {}
