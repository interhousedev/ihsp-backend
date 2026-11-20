"""Both migration scripts against fake host tools: no Docker, no SSH, no root."""

import base64
import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "migrate_runner.sh"
TARGET = ROOT / "scripts" / "migrate_target.sh"

# Logs every call; answers the few queries the scripts read back.
FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
args=" $* "
case "$args" in
    *" LASTSAVE "*)
        n=$(cat "$FAKE_STATE/lastsave" 2> /dev/null || echo 0)
        echo $((n + 1)) > "$FAKE_STATE/lastsave"; echo "$n" ;;
    *" vault status "*) echo "Sealed          false" ;;
    *" pg_dump "*) echo "DUMP ${@: -1}" ;;
    *"pg_database"*) [ "${FAKE_BUGSINK_DB:-0}" = 1 ] && echo 1 ;;
    *" ps -q s3 "*) [ "${FAKE_S3:-1}" = 1 ] && echo cid-s3 ;;
    *" cp cid-s3:/data/. - "*) echo OBJECTS ;;
    *" compose "*" cp "*) echo "COPY" > "${@: -1}" ;;
    *" exec -T vault sh -c "*"mktemp"*) cat > /dev/null; echo /tmp/vault-restore.x ;;
    *"query_to_xml"*) echo "public|${FAKE_ROWS:-42}" ;;
    *" DBSIZE "*) echo 42 ;;
    *"find /data -type f"*) echo 7 ;;
    *"alembic heads"*) echo "rev1 (ihsp) (head)" ;;
    *"alembic current"*) echo "${FAKE_CURRENT:-rev1 (ihsp) (head)}" ;;
    *) [ -t 0 ] || cat > /dev/null ;;
esac
exit 0
"""

# rsync user@host:ID/ -> $FAKE_DEST/ID/
FAKE_RSYNC = r"""#!/usr/bin/env bash
src=${@: -2:1}; dst=${@: -1}; dst=$FAKE_DEST/${dst#*:}
mkdir -p "$(dirname "$dst")"
if [ -d "$src" ]; then mkdir -p "$dst" && cp -R "$src". "$dst"
else cp "$src" "$dst"; fi
"""

FAKE_ID = """#!/usr/bin/env bash
[ "$1" = -u ] && { echo 0; exit 0; }
exit 0
"""

# install -d [-m M] [-o U] [-g G] DIR...: only the directories.
FAKE_INSTALL = """#!/usr/bin/env bash
while [ $# -gt 0 ]; do
    case "$1" in -d) shift ;; -m|-o|-g) shift 2 ;; *) mkdir -p "$1"; shift ;; esac
done
"""


def _bin(tmp: Path) -> Path:
    path = tmp / "bin"
    path.mkdir()
    tools = {
        "docker": FAKE_DOCKER,
        "rsync": FAKE_RSYNC,
        "id": FAKE_ID,
        "install": FAKE_INSTALL,
        "useradd": "#!/bin/sh\n",
        "passwd": "#!/bin/sh\n",
        "chown": "#!/bin/sh\n",
        "rrsync": "#!/bin/sh\n",
        "flock": "#!/bin/sh\n",
        "pkill": '#!/bin/sh\necho "pkill $*" >> "$FAKE_LOG"\n',
    }
    for name, body in tools.items():
        (path / name).write_text(body, encoding="utf-8")
        (path / name).chmod(0o755)
    return path


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    state = tmp / "state"
    state.mkdir(exist_ok=True)
    return {
        **os.environ,
        "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "IHSP_ROOT": str(tmp / "root"),
        "FAKE_LOG": str(tmp / "docker.log"),
        "FAKE_STATE": str(state),
        "FAKE_DEST": str(tmp / "dest"),
        "TMPDIR": str(tmp / "tmpdir"),
        **extra,
    }


def _install(tmp: Path, env_lines: list[str]) -> Path:
    root = tmp / "root"
    for sub in ("materials", "secrets", "backups"):
        (root / sub).mkdir(parents=True)
    (root / ".env.prod").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    (root / "materials" / "docker-compose.prod.yaml").write_text("services: {}\n")
    (root / "backups" / "b.dump.age").write_text("backup")
    (tmp / "tmpdir").mkdir()
    _bin(tmp)
    return root


def _log(tmp: Path) -> list[str]:
    path = tmp / "docker.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _run(
    script: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# --- target: prepare ---------------------------------------------------------------


def test_prepare_succeeds_and_leaves_no_private_key_behind(tmp_path: Path) -> None:
    _install(tmp_path, ["POSTGRES_PASSWORD=x"])
    host_key = tmp_path / "host.pub"
    host_key.write_text("ssh-ed25519 AAAAHOST root@new\n")
    env = _env(
        tmp_path,
        IHSP_MIGRATE_HOME=str(tmp_path / "home"),
        IHSP_SSH_HOST_KEY=str(host_key),
    )
    done = _run(TARGET, env, "prepare", "--host", "new.example.com")
    # The EXIT trap once failed with "tmp: unbound variable" (exit 1 after success).
    assert done.returncode == 0, done.stderr
    assert "unbound" not in done.stderr
    assert list((tmp_path / "tmpdir").iterdir()) == []
    token = done.stdout.strip().splitlines()[-1]
    raw = token.split(".", 1)[1]
    body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert body["host_key"] == "ssh-ed25519 AAAAHOST"
    assert "PRIVATE KEY" in body["key"]
    keys = (tmp_path / "home" / ".ssh" / "authorized_keys").read_text()
    assert keys.startswith('restrict,command="')


# --- target: finish ----------------------------------------------------------------

TARGET_ENV = [
    "POSTGRES_PASSWORD=target-pg",
    "HYDRA_DB_PASSWORD=target-hydra",
    "BUGSINK_DB_PASSWORD=target-bugsink",
]
SOURCE_ENV = [
    "POSTGRES_PASSWORD=source-pg",
    "HYDRA_DB_PASSWORD=source-hydra",
    "BUGSINK_DB_PASSWORD=source-bugsink",
]


# What the old server counted right after its dump (scripts/migration_counts.sh).
SOURCE_COUNTS = (
    "ihsp\tpublic\t42\n"
    "hydra\tpublic\t42\n"
    "bugsink\tpublic\t42\n"
    "redis\tkeys\t42\n"
    "s3\tobjects\texternal\n"
    "vault\tsealed\tfalse\n"
)


def _received(tmp: Path, *, objects: bool = True, mode: str = "main") -> Path:
    """A complete transfer as the runner leaves it in incoming/<id>."""
    src = tmp / "src-config"
    (src / "materials").mkdir(parents=True)
    (src / "secrets").mkdir()
    (src / "materials" / "docker-compose.prod.yaml").write_text("services: {}\n")
    (src / ".env.prod").write_text(
        "\n".join([*SOURCE_ENV, f"BUGSINK_DB_MODE={mode}"]) + "\n"
    )
    out = tmp / "root" / "incoming" / "m-1"
    out.mkdir(parents=True)
    with tarfile.open(out / "config.tar", "w") as tar:
        for name in (".env.prod", "secrets", "materials"):
            tar.add(src / name, arcname=name)
    files = ["ihsp.dump", "hydra.dump", "bugsink.dump", "redis.rdb", "vault.snap"]
    if objects:
        files.append("s3_data.tar")
    for name in files:
        (out / name).write_text(f"data of {name}")
    (out / "counts.tsv").write_text(SOURCE_COUNTS)
    sums = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.name}"
        for p in sorted(out.iterdir())
    ]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    (out / "READY").write_text("m-1\n")
    return out


def _finish_setup(tmp: Path, **kw: object) -> tuple[Path, dict[str, str]]:
    root = _install(tmp, TARGET_ENV)
    (root / "secrets" / "vault-init.txt").write_text(
        "Unseal Key 1: k1\nUnseal Key 2: k2\nUnseal Key 3: k3\n"
        "Initial Root Token: target-root\n"
    )
    home = tmp / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "authorized_keys").write_text("restrict key\n")
    _received(tmp, **kw)  # type: ignore[arg-type]
    return root, _env(tmp, IHSP_MIGRATE_HOME=str(home), FAKE_BUGSINK_DB="1")


def test_finish_refuses_an_incomplete_transfer(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    (tmp_path / "root" / "incoming" / "m-1" / "READY").unlink()
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode != 0
    assert "READY is missing" in done.stderr
    assert (tmp_path / "home" / ".ssh" / "authorized_keys").exists()
    assert _log(tmp_path) == []


STAGED = Path("root") / "migration-staging" / "m-1"


def test_finish_freezes_the_set_before_checking_it(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    (tmp_path / "root" / "incoming" / "m-1" / "ihsp.dump").write_text("tampered")
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode != 0
    assert "checksum mismatch" in done.stderr
    # Revoked and sessions killed first, then checked on the root-only staged copy.
    assert not (tmp_path / "home" / ".ssh" / "authorized_keys").exists()
    assert _log(tmp_path) == ["pkill -KILL -u ihsp-migrate"]
    assert not (tmp_path / "root" / "incoming" / "m-1").exists()
    assert (tmp_path / STAGED / "READY").exists()


def test_finish_checks_every_dump_before_stopping_anything(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    out = tmp_path / "root" / "incoming" / "m-1"
    (out / "redis.rdb").write_text("")
    sums = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.name}"
        for p in sorted(out.iterdir())
        if p.name not in ("SHA256SUMS", "READY")
    ]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode != 0
    assert "redis.rdb is missing or empty" in done.stderr
    assert not any("down" in line for line in _log(tmp_path))


def _index(log: list[str], needle: str) -> int:
    return next(i for i, line in enumerate(log) if needle in line)


def test_finish_restores_everything_with_owners(tmp_path: Path) -> None:
    root, env = _finish_setup(tmp_path)
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 0, done.stderr
    log = _log(tmp_path)
    assert not (tmp_path / "home" / ".ssh" / "authorized_keys").exists()
    # The copied config replaced this server's; the old one is kept aside.
    assert "source-pg" in (root / ".env.prod").read_text()
    assert (root / "config-before-migration.tar").exists()
    assert (root / "backups" / "b.dump.age").exists()
    # Roles get the copied passwords, databases come back with their owners.
    assert any("psql" in line and "POSTGRES_PASSWORD" in line for line in log)
    restores = [line for line in log if "pg_restore -U" in line]
    assert len(restores) == 3
    assert all("--exit-on-error" in r and "--no-owner" not in r for r in restores)
    # Every dump was listed before the stack went down.
    down = _index(log, "--profile * down")
    assert sum("pg_restore -l" in line for line in log[:down]) == 3
    # The pre-migration config is private.
    assert (root / "config-before-migration.tar").stat().st_mode & 0o777 == 0o600
    for db, owner in (("ihsp", "ihsp"), ("hydra", "hydra"), ("bugsink", "bugsink")):
        assert any(f"createdb -U ihsp -O {owner} {db}" in line for line in log)
        assert any(f"dropdb -U ihsp --if-exists --force {db}" in line for line in log)
    # Object store is replaced, not merged.
    wipe = _index(log, "find /data -mindepth 1 -delete")
    assert _index(log, "cp - cid-s3:/data") > wipe
    # Redis: the shared loader, which checks PONG, CONFIG SET and the AOF manifest.
    text = "\n".join(log)
    assert text.index("redis-cli CONFIG SET appendonly yes") > text.index(
        "redis-server --appendonly no"
    )
    assert "appendonlydir/*.manifest" in text
    # Vault: unsealed with this server's keys (never in an argv), the snapshot forced,
    # the keys retired.
    assert sum("/v1/sys/unseal" in line for line in log) == 3
    assert sum("--post-file" in line for line in log) == 3
    assert not any("k1" in line or "k2" in line for line in log)
    assert any("snapshot restore -force /tmp/vault-restore.x" in line for line in log)
    assert not (root / "secrets" / "vault-init.txt").exists()
    assert (root / "secrets" / "vault-init.before-migration.txt").exists()
    assert "unseal" in done.stderr
    assert "BUGSINK_DB_HOST=postgres docker compose" in done.stderr
    assert (tmp_path / STAGED / "RESTORED").exists()
    # A restored set is never restored twice.
    again = _run(TARGET, env, "finish", "m-1")
    assert again.returncode != 0
    assert "already restored" in again.stderr


def test_finish_keeps_an_existing_pre_migration_config(tmp_path: Path) -> None:
    root, env = _finish_setup(tmp_path)
    (root / "config-before-migration.tar").write_text("first")
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 0, done.stderr
    assert (root / "config-before-migration.tar").read_text() == "first"


def test_finish_fails_loudly_when_vault_is_skipped(tmp_path: Path) -> None:
    root, env = _finish_setup(tmp_path)
    (root / "secrets" / "vault-init.txt").unlink()
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 3
    assert "Vault was NOT restored" in done.stderr


def test_finish_creates_the_bugsink_role_in_main_mode(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 0, done.stderr
    log = _log(tmp_path)
    create = _index(log, 'pw="$BUGSINK_PW"')
    assert create < _index(log, "createdb -U ihsp -O bugsink bugsink")
    assert not any("source-bugsink" in line for line in log)


def test_finish_restores_a_dedicated_bugsink_db(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path, mode="dedicated")
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 0, done.stderr
    log = _log(tmp_path)
    assert any(
        "--profile bugsink-dedicated exec -T bugsink-db pg_restore -U bugsink" in line
        for line in log
    )
    assert "COMPOSE_PROFILES=bugsink-dedicated" in done.stderr


def test_finish_skips_an_external_object_store(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path, objects=False)
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 0, done.stderr
    assert "nothing to restore" in done.stderr
    assert not any("find /data" in line for line in _log(tmp_path))


def test_finish_checks_every_store_against_the_source_counts(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 0, done.stderr
    assert "verification" in done.stderr
    assert "MISMATCH" not in done.stderr
    for row in ("ihsp", "hydra", "bugsink", "redis", "s3", "vault", "alembic"):
        assert row in done.stderr
    assert (tmp_path / STAGED / "RESTORED").exists()


def test_finish_refuses_a_row_count_mismatch(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    env["FAKE_ROWS"] = "41"
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 4
    assert "MISMATCH" in done.stderr
    assert not (tmp_path / STAGED / "RESTORED").exists()


def test_finish_refuses_when_alembic_is_not_at_the_heads(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    env["FAKE_CURRENT"] = "rev0 (ihsp) (head)"
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode == 4
    assert "alembic" in done.stderr
    assert "MISMATCH" in done.stderr


def test_finish_refuses_a_transfer_without_counts(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    out = tmp_path / "root" / "incoming" / "m-1"
    (out / "counts.tsv").unlink()
    sums = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.name}"
        for p in sorted(out.iterdir())
        if p.name not in ("SHA256SUMS", "READY")
    ]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    done = _run(TARGET, env, "finish", "m-1")
    assert done.returncode != 0
    assert "counts.tsv is missing" in done.stderr
    assert not any("down" in line for line in _log(tmp_path))


def test_abort_before_a_restore_drops_the_data(tmp_path: Path) -> None:
    _, env = _finish_setup(tmp_path)
    done = _run(TARGET, env, "abort")
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "home" / ".ssh" / "authorized_keys").exists()
    assert list((tmp_path / "root" / "incoming").iterdir()) == []
    assert not any("down" in line for line in _log(tmp_path))


def test_abort_after_a_restore_stops_the_stack_and_keeps_artifacts(
    tmp_path: Path,
) -> None:
    root, env = _finish_setup(tmp_path)
    assert _run(TARGET, env, "finish", "m-1").returncode == 0
    (tmp_path / "docker.log").unlink()
    done = _run(TARGET, env, "abort")
    assert done.returncode == 0, done.stderr
    assert any("--profile * down" in line for line in _log(tmp_path))
    assert "confirm nothing runs here" in done.stderr
    assert (tmp_path / STAGED / "ihsp.dump").exists()
    assert (root / "config-before-migration.tar").exists()


def _loader(tmp: Path, cli: str) -> subprocess.CompletedProcess[str]:
    """scripts/redis_load_rdb.sh with fake redis-server, redis-cli and sleep."""
    bin_ = tmp / "rbin"
    bin_.mkdir()
    for name, body in {
        "redis-server": "#!/bin/sh\n",
        "redis-cli": cli,
        "sleep": "#!/bin/sh\n",
    }.items():
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(0o755)
    (tmp / "data").mkdir()
    (tmp / "restore").mkdir()
    (tmp / "restore" / "redis.rdb").write_text("RDB")
    env = {
        **os.environ,
        "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
        "IHSP_REDIS_DATA": str(tmp / "data"),
        "IHSP_REDIS_RESTORE": str(tmp / "restore"),
        "REDIS_PASSWORD": "pw",
    }
    return subprocess.run(
        ["sh", str(ROOT / "scripts" / "redis_load_rdb.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# $1 picks the answer; the AOF manifest appears once CONFIG SET ran (when allowed).
REDIS_CLI = r"""#!/bin/sh
case "$1" in
    ping) [ "${PONG:-1}" = 1 ] && echo PONG || echo "Could not connect" ;;
    DBSIZE) echo 42 ;;
    CONFIG) echo "${CONFIG_ANSWER:-OK}"
        [ "${MANIFEST:-1}" = 1 ] && mkdir -p "$IHSP_REDIS_DATA/appendonlydir" \
            && touch "$IHSP_REDIS_DATA/appendonlydir/appendonly.aof.manifest" ;;
    INFO) printf 'loading:0\r\naof_rewrite_in_progress:0\r\n'
        printf 'aof_rewrite_scheduled:0\r\naof_last_bgrewrite_status:ok\r\n' ;;
esac
exit 0
"""


def test_the_redis_loader_reports_the_key_count(tmp_path: Path) -> None:
    done = _loader(tmp_path, REDIS_CLI)
    assert done.returncode == 0, done.stderr
    assert "42 keys loaded" in done.stderr


@pytest.mark.parametrize(
    ("var", "message"),
    [
        ("PONG=0", "did not answer PONG"),
        ("CONFIG_ANSWER=ERR", "CONFIG SET appendonly yes failed"),
        ("MANIFEST=0", "no manifest"),
    ],
)
def test_the_redis_loader_fails_on_what_it_cannot_confirm(
    tmp_path: Path, var: str, message: str
) -> None:
    done = _loader(tmp_path, REDIS_CLI.replace("#!/bin/sh\n", f"#!/bin/sh\n{var}\n"))
    assert done.returncode != 0
    assert message in done.stderr


# --- runner: a real (non-dry) run against fakes ------------------------------------


def _token() -> str:
    body = {
        "user": "ihsp-migrate",
        "port": 22,
        "key": "KEY",
        "host_key": "ssh-ed25519 A",
    }
    return (
        "ihsp-pair-v1." + base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    )


def _runner(
    tmp: Path, env_lines: list[str], expect: str = "completed", **extra: str
) -> Path:
    _install(tmp, [*env_lines, "VAULT_BACKUP_ROLE_ID=r", "VAULT_BACKUP_SECRET_ID=s"])
    queue = tmp / "queue"
    queue.mkdir()
    request = {
        "id": "m-1",
        "target_host": "new.example.com",
        "target_port": 22,
        "pairing_token": _token(),
        "requested_at": "2026-01-01T00:00:00+00:00",
        "dry_run": False,
    }
    (queue / "request.json").write_text(json.dumps(request))
    (queue / "request.json").chmod(0o600)
    env = _env(
        tmp,
        IHSP_MIGRATION_DIR=str(queue),
        IHSP_MIGRATION_WORK=str(tmp / "work"),
        **extra,
    )
    done = _run(RUNNER, env, "run")
    status = json.loads((queue / "status.json").read_text())
    assert status["state"] == expect, done.stdout + done.stderr
    return tmp / "dest" / "m-1"


@pytest.mark.parametrize(
    ("mode", "fake_db", "needle"),
    [
        ("dedicated", "0", "--profile bugsink-dedicated exec -T bugsink-db pg_dump"),
        ("main", "1", "exec -T postgres pg_dump -U ihsp -Fc bugsink"),
    ],
)
def test_the_runner_carries_bugsink(
    tmp_path: Path, mode: str, fake_db: str, needle: str
) -> None:
    dest = _runner(
        tmp_path,
        [f"BUGSINK_DB_MODE={mode}", "IHSP_S3__ENDPOINT_URL=http://s3:9000"],
        FAKE_BUGSINK_DB=fake_db,
    )
    assert (dest / "bugsink.dump").read_text().startswith("DUMP bugsink")
    assert any(needle in line for line in _log(tmp_path))
    assert (dest / "s3_data.tar").read_text() == "OBJECTS\n"
    assert (dest / "READY").exists()


def test_the_runner_counts_every_store_before_the_transfer(tmp_path: Path) -> None:
    dest = _runner(tmp_path, ["IHSP_S3__ENDPOINT_URL=http://s3:9000"])
    counts = (dest / "counts.tsv").read_text(encoding="utf-8").splitlines()
    assert "ihsp\tpublic\t42" in counts
    assert "redis\tkeys\t42" in counts
    assert "s3\tobjects\t7" in counts
    assert "vault\tsealed\tfalse" in counts


def test_the_runner_skips_bugsink_when_it_has_no_database(tmp_path: Path) -> None:
    dest = _runner(tmp_path, ["IHSP_S3__ENDPOINT_URL=http://s3:9000"])
    assert not (dest / "bugsink.dump").exists()
    assert (dest / "ihsp.dump").exists()


def test_the_runner_leaves_an_external_object_store_alone(tmp_path: Path) -> None:
    dest = _runner(
        tmp_path, ["IHSP_S3__ENDPOINT_URL=https://storage.example.com"], FAKE_S3="0"
    )
    assert not (dest / "s3_data.tar").exists()


@pytest.mark.parametrize(
    "url", ["http://s3", "http://s3/", '"http://s3:9000"', "'https://s3:9000/'"]
)
def test_the_runner_recognises_the_bundled_object_store(
    tmp_path: Path, url: str
) -> None:
    dest = _runner(tmp_path, [f"IHSP_S3__ENDPOINT_URL={url}"])
    assert (dest / "s3_data.tar").read_text() == "OBJECTS\n"


def test_the_runner_refuses_an_external_url_next_to_a_bundled_store(
    tmp_path: Path,
) -> None:
    _runner(tmp_path, ["IHSP_S3__ENDPOINT_URL=https://s3.example.com"], "failed")
    status = (tmp_path / "queue" / "status.json").read_text()
    assert "not the bundled one" in status
