"""Migration gate: scripts/check_migrations.sh runs this file.

On a throw-away database of the dev compose postgres it checks that
  1. ``alembic heads`` loads;
  2. ``alembic upgrade heads`` builds the schema from empty and the ORM metadata
     agrees with it (empty autogenerate diff, as tests/models/test_migrations.py);
  3. the manual-migration rehearsal works: upgrade to every head minus the
     revisions added on this branch, then ``alembic upgrade heads`` again.
"""

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.db.base import Base  # noqa: E402,F401
from tests.models.conftest import DEFAULT_URL  # noqa: E402
from tests.models.test_migrations import _compare  # noqa: E402

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


def say(message: str) -> None:
    print(f"[check_migrations] {message}", flush=True)


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "IHSP_DATABASE__URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, check=True
    )


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else ""


def new_revision_files() -> set[str]:
    """Return migration files added on this branch (committed, staged or untracked)."""
    base = ""
    for ref in ("origin/main", "main"):
        base = git("merge-base", "HEAD", ref).strip()
        if base:
            break
    files: set[str] = set()
    if base:
        files |= set(
            git(
                "diff",
                "--name-only",
                "--diff-filter=A",
                base,
                "--",
                "migrations/versions",
            ).split()
        )
    files |= set(
        git(
            "ls-files", "--others", "--exclude-standard", "--", "migrations/versions"
        ).split()
    )
    return {f for f in files if f.endswith(".py")}


def revisions_of(files: set[str]) -> set[str]:
    found: set[str] = set()
    for name in files:
        text = (ROOT / name).read_text()
        match = re.search(r'^revision(?::[^=]*)?=\s*"([^"]+)"', text, re.M)
        if match:
            found.add(match.group(1))
    return found


def rehearsal_targets(new: set[str]) -> list[str]:
    """Return the revisions to upgrade to so that only ``new`` revisions are missing."""
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    targets: list[str] = []
    for head in script.get_heads():
        stack = [head]
        seen: set[str] = set()
        while stack:
            rev_id = stack.pop()
            if rev_id in seen:
                continue
            seen.add(rev_id)
            rev = script.get_revision(rev_id)
            if rev_id not in new:
                targets.append(rev_id)
                continue
            (
                stack.extend(d for d in (rev.down_revision or ()) if d)
                if not isinstance(rev.down_revision, str)
                else stack.append(rev.down_revision)
            )
    return sorted(set(targets))


async def server(sql: str, url: str) -> None:
    u = make_url(url)
    conn = await asyncpg.connect(
        host=u.host,
        port=u.port,
        user=u.username,
        password=u.password,
        database="postgres",
    )
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def diff(url: str) -> list[object]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(_compare)
    finally:
        await engine.dispose()


async def main() -> int:
    base_url = os.environ.get("IHSP_DATABASE__URL", DEFAULT_URL)
    try:
        await server("SELECT 1", base_url)
    except OSError as exc:
        say(f"postgres unreachable ({exc}); start the dev compose services")
        return 2
    name = f"ihsp_migcheck_{os.getpid()}"
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    await server(f'CREATE DATABASE "{name}"', base_url)
    try:
        say("1/4 alembic heads loads")
        alembic(url, "heads")

        say("2/4 upgrade heads from empty")
        alembic(url, "upgrade", "heads")
        differences = await diff(url)
        if differences:
            say(f"ORM metadata differs from the migrated schema: {differences}")
            return 1
        say("   metadata matches the migrated schema")
    finally:
        pass

    try:
        new = revisions_of(new_revision_files())
        if not new:
            say("3/4 rehearsal skipped: no migration is new on this branch")
        else:
            say(f"3/4 rehearsal: {len(new)} new revisions: {sorted(new)}")
            await server(f'DROP DATABASE "{name}" WITH (FORCE)', base_url)
            await server(f'CREATE DATABASE "{name}"', base_url)
            for target in rehearsal_targets(new):
                alembic(url, "upgrade", target)
            say("4/4 upgrade heads on the existing database")
            alembic(url, "upgrade", "heads")
            differences = await diff(url)
            if differences:
                say(f"schema differs after the rehearsal: {differences}")
                return 1
        say("OK")
        return 0
    finally:
        await server(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', base_url)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
