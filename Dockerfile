# Backend image: one image for every process (`python -m app <process>`; compose sets the command).
#
#   docker build -t ihsp-backend:dev .      # the build context is the repo root (see .dockerignore)
#
# Builder: the locked runtime dependencies only, into /app/.venv (uv, bytecode compiled, cache mounts).
# The project itself is not installed: the app resolves its locales, migrations and alembic.ini from the
# source tree (app/shared/paths.py: BACKEND_ROOT is the directory above the package), so the source is
# copied next to the venv instead of into site-packages.
#
# Runtime: the same Python base image, the venv and the source. The only OS package added is libmagic1
# (python-magic loads it when the file sniffer is used). No uv, no pip, no compiler, no git, no shell
# history. The wheels bundle their own native libraries (asyncpg, cryptography, lxml, pypdfium2, ...).

FROM python:3.14.7-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies only: pyproject.toml and uv.lock are bind-mounted, so no source enters this stage.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------------------------------
FROM python:3.14.7-slim AS runtime

# python-magic needs libmagic at import time. Nothing else needs an OS package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# The base image's own pip and setuptools are not used at runtime (the venv has its own packages).
RUN site="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && rm -rf "$site/pip" "$site"/pip-*.dist-info \
              "$site/setuptools" "$site"/setuptools-*.dist-info "$site/_distutils_hack" \
              "$site/pkg_resources" "$site/wheel" "$site"/wheel-*.dist-info \
              "$site/distutils-precedence.pth" \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
             /usr/local/bin/easy_install /usr/local/bin/easy_install-3.13

# Unprivileged runtime user, fixed ids (checkable by orchestrators), no login shell, no home directory.
RUN groupadd --system --gid 10001 ihsp \
    && useradd --system --no-log-init --uid 10001 --gid ihsp \
               --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin ihsp

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY locales ./locales
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

# Bytecode is compiled now: the runtime user cannot write __pycache__ under /app (read-only for it)
RUN python -m compileall -q app migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    TMPDIR=/tmp

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG SOURCE=
LABEL org.opencontainers.image.title="ihsp-backend" \
      org.opencontainers.image.description="IHSP backend: one image for every process (python -m app <process>)" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.version="${VERSION}"

# No HEALTHCHECK here: the processes differ (HTTP on 8000, 8001 and 8002; mail, worker and scheduler
# have no HTTP port). Each compose service sets its own probe (materials/healthcheck/check.py).
USER 10001:10001

# One image, many processes: identity, api, bot, mail, worker, scheduler, migrate (compose overrides this).
CMD ["python", "-m", "app", "api"]
