# Backend image. Build context is ./backend; config/ is mounted at runtime
# (docker-compose.yml), so the layout mirrors the repo: /app/backend + /app/config,
# which makes app.settings.REPO_ROOT resolve to /app.

# --- build: resolve dependencies into a venv with uv ---
# Same base as the runtime stage, so the venv's python symlinks stay valid when copied.
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend

# Dependencies first so code changes don't invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-dev --no-install-project

# --- runtime: plain python, no uv or build tooling ---
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH=/app/backend/.venv/bin:$PATH
WORKDIR /app/backend

RUN useradd --system --uid 10001 --no-create-home lingo
COPY --from=build /app/backend/.venv .venv
COPY alembic.ini ./
COPY app app

USER lingo
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# Migrations are idempotent (Alembic + checkpointer setup), so running them on every
# start keeps "docker compose up" a one-step deploy. Single worker: low-memory target.
CMD ["sh", "-c", "python -m app.db.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
