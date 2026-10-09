"""The test fixtures themselves and the dev compose stack they rely on."""

from collections.abc import Callable

from app.settings import Settings
from app.shared.actor import Actor, Role
from tests.conftest import S3_CONFIG, TEST_DB_NAME
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

from aiobotocore.session import get_session
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_settings_point_at_the_session_database(settings: Settings) -> None:
    """The settings fixture names the fresh per-session database."""
    assert settings.env == "test"
    assert settings.database.url.endswith(f"/{TEST_DB_NAME}")


async def test_a_session_commit_is_visible_inside_the_test(
    db_session: AsyncSession,
) -> None:
    """Commits release a SAVEPOINT, so the test sees its own data."""
    await db_session.execute(text("CREATE TABLE public.harness_probe (v int)"))
    await db_session.execute(text("INSERT INTO public.harness_probe VALUES (1)"))
    await db_session.commit()

    count = await db_session.scalar(text("SELECT count(*) FROM public.harness_probe"))

    assert count == 1


async def test_the_previous_tests_data_is_rolled_back(
    db_session: AsyncSession,
) -> None:
    """The outer transaction is rolled back after every test (runs after the above)."""
    exists = await db_session.scalar(text("SELECT to_regclass('public.harness_probe')"))

    assert exists is None


async def test_every_schema_and_table_is_created(db_session: AsyncSession) -> None:
    """The engine fixture creates every module schema."""
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.schemata WHERE schema_name IN "
            "('id','academic','files','links','ai','notify','admin','mail','lms')"
        )
    )

    assert result.scalar_one() == 9


async def test_the_clock_and_kicker_fixtures(
    clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """Fixed time and a recording kicker."""
    await kicker.kick("notify.dispatch_due", batch=1)

    assert clock.now().isoformat() == "2026-10-06T09:00:00+00:00"
    assert kicker.calls == [("notify.dispatch_due", {"batch": 1})]


def test_make_actor_builds_actors(make_actor: Callable[..., Actor]) -> None:
    """make_actor(*roles, user_id=None, **kw)."""
    actor = make_actor(Role.TEACHER, Role.ADMIN, client_id="staff")

    assert actor.roles == {Role.TEACHER, Role.ADMIN}
    assert actor.client_id == "staff"


async def test_redis_starts_empty_and_decodes_strings(redis: Redis) -> None:
    """fakeredis returns str like the production client."""
    assert await redis.get("k") is None

    await redis.set("k", "v")

    assert await redis.get("k") == "v"


async def test_s3_bucket_fixture_gives_a_working_bucket(
    settings: Settings, s3_bucket: str
) -> None:
    """The compose S3 server stores and returns objects."""
    async with get_session().create_client(
        "s3",
        endpoint_url=settings.s3.endpoint_url,
        aws_access_key_id=settings.s3.access_key,
        aws_secret_access_key=settings.s3.secret_key.get_secret_value(),
        region_name=settings.s3.region,
        config=S3_CONFIG,
    ) as s3:
        await s3.put_object(Bucket=s3_bucket, Key="a.txt", Body=b"hello")
        response = await s3.get_object(Bucket=s3_bucket, Key="a.txt")
        async with response["Body"] as stream:
            data = await stream.read()

    assert data == b"hello"


async def test_the_dev_bucket_exists_with_browser_upload_cors(
    settings: Settings,
) -> None:
    """s3-init created ihsp-dev and allows PUT/GET from the web origins.

    The six apps on 3001-3006 and the library on 3008, which uploads and reads book
    files straight from the bucket.
    """
    async with get_session().create_client(
        "s3",
        endpoint_url=settings.s3.endpoint_url,
        aws_access_key_id=settings.s3.access_key,
        aws_secret_access_key=settings.s3.secret_key.get_secret_value(),
        region_name=settings.s3.region,
        config=S3_CONFIG,
    ) as s3:
        await s3.head_bucket(Bucket=settings.s3.bucket)
        rules = (await s3.get_bucket_cors(Bucket=settings.s3.bucket))["CORSRules"]

    origins = {origin for rule in rules for origin in rule["AllowedOrigins"]}
    methods = {method for rule in rules for method in rule["AllowedMethods"]}
    ports = [*range(3001, 3007), 3008]
    assert origins == {f"http://localhost:{port}" for port in ports}
    assert {"PUT", "GET"} <= methods
