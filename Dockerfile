FROM python:3.13-slim

# libmagic: file type sniffing (python-magic)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# Processes run as an unprivileged user; /app is read-only for it.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin ihsp
USER ihsp

# One image, many processes: `python -m app <process>` (identity, api, bot, mail, worker, scheduler).
CMD ["python", "-m", "app", "api"]
