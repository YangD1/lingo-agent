"""Start the real backend for Playwright on a freshly recreated `lingo_e2e` database.

Run from frontend/: `uv run --project ../backend python e2e/run_backend.py`.
Separate from pytest's `lingo_test` so the two never wipe each other's data.
"""

import asyncio
import bz2
import os
import sys
import tempfile
from pathlib import Path

import psycopg

PORT = os.environ.get("E2E_BACKEND_PORT", "8100")
# The server to test against, via its maintenance database; lingo_e2e is created next to it.
ADMIN_URL = os.environ.get("E2E_ADMIN_DB", "postgresql://lingo:lingo@localhost:5433/postgres")
DB_NAME = "lingo_e2e"
# A small real slice of ECDICT: the Oxford 3000 book has 7 of its words.
WORDS_CSV = Path(__file__).parents[2] / "backend" / "tests" / "fixtures" / "ecdict_sample.csv"
# Two Tatoeba sentences for "go" (one by an inflected form, one in traditional Chinese
# that the import simplifies), in the export layout import_tatoeba reads.
TATOEBA = {
    "eng_sentences.tsv.bz2": "1\teng\tI went to school by bus yesterday.\n"
    "2\teng\tLet's go home together now.\n",
    "cmn_sentences.tsv.bz2": "10\tcmn\t我昨天坐公交车去上学。\n11\tcmn\t我們現在一起回家吧。\n",
    "cmn-eng_links.tsv.bz2": "10\t1\n11\t2\n",
}
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
    # Tests drive background work themselves; no scheduled jobs firing mid-test.
    SCHEDULER_ENABLED="false",
)


def recreate_database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {DB_NAME}")


async def import_sentences() -> None:
    from app.services.vocab.import_tatoeba import import_dir

    with tempfile.TemporaryDirectory() as directory:
        for name, body in TATOEBA.items():
            (Path(directory) / name).write_bytes(bz2.compress(body.encode()))
        await import_dir(os.environ["DATABASE_URL"], Path(directory))


def main() -> None:
    recreate_database()
    from app.db.migrate import main as migrate
    from app.services.vocab.import_ecdict import import_csv

    migrate()
    asyncio.run(import_csv(os.environ["DATABASE_URL"], WORDS_CSV))
    asyncio.run(import_sentences())
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
