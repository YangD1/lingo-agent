"""Start the real backend for Playwright on a freshly recreated `lingo_e2e` database.

Run from frontend/: `uv run --project ../backend python e2e/run_backend.py`.
Separate from pytest's `lingo_test` so the two never wipe each other's data.
"""

import os
import sys

import psycopg

PORT = os.environ.get("E2E_BACKEND_PORT", "8100")
# The server to test against, via its maintenance database; lingo_e2e is created next to it.
ADMIN_URL = os.environ.get("E2E_ADMIN_DB", "postgresql://lingo:lingo@localhost:5433/postgres")
DB_NAME = "lingo_e2e"
SERVER = ADMIN_URL.split("://", 1)[1].rsplit("/", 1)[0]  # user:password@host:port

# Throwaway values for a local test database only - never used anywhere else.
os.environ.update(
    APP_ENV="dev",
    DATABASE_URL=f"postgresql+psycopg://{SERVER}/{DB_NAME}",
    JWT_SECRET="e2e-only-jwt-secret-not-for-production-use",
    CREDENTIALS_ENCRYPTION_KEYS="e2e:" + "A" * 43 + "=",
    # The fake LLM server listens on localhost.
    PROVIDER_ALLOW_PRIVATE_NETWORKS="true",
    LANGSMITH_TRACING="false",
)


def recreate_database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {DB_NAME}")


def main() -> None:
    recreate_database()
    from app.db.migrate import main as migrate

    migrate()
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            PORT,
            "--app-dir",
            "../backend",
        ],
    )


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
    main()
