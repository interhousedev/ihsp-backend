"""RuntimeSettingsService caches for `ttl` seconds."""

from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from tests.admission.unit.fakes import FakeStore, FakeUow


async def test_cache_reloads_after_ttl_and_invalidate() -> None:
    store = FakeStore()
    store.runtime = {"flag": 1}
    now = [100.0]
    service = RuntimeSettingsService(
        lambda: FakeUow(store), ttl=30.0, monotonic=lambda: now[0]
    )
    assert (await service.get()).get("flag") == 1
    store.runtime = {"flag": 2}
    now[0] += 29.9
    assert (await service.get()).get("flag") == 1
    assert store.runtime_loads == 1
    now[0] += 0.2
    assert (await service.get()).get("flag") == 2
    store.runtime = {"flag": 3}
    service.invalidate()
    assert (await service.get()).get("flag") == 3
    assert store.runtime_loads == 3
