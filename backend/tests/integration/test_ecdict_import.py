"""Loading ECDICT into `words` (ADR 0011): COPY + upsert, safe to repeat."""

import hashlib
from pathlib import Path

import anyio
import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models import Word
from app.services.vocab.import_ecdict import DownloadError, download, import_csv
from tests.conftest import TEST_DATABASE_URL

SAMPLE = Path(__file__).parents[1] / "fixtures" / "ecdict_sample.csv"


async def test_import_is_repeatable_and_updates_changed_rows(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    stats, changed = await import_csv(TEST_DATABASE_URL, SAMPLE)
    assert (stats.read, stats.kept, changed) == (27, 18, 18)
    go = await db_session.scalar(select(Word).where(Word.word == "go"))
    assert go is not None
    assert go.tags == ["gk", "ielts", "zk"] and go.frq == 35 and go.oxford
    assert go.exchange and "0:" not in go.exchange  # "go" is itself the lemma
    held = await db_session.scalar(select(Word).where(Word.word == "held"))
    assert held is not None and held.exchange == "0:hold/1:dp/p:held/d:held"

    # Again: nothing changes, ids stay.
    _, changed = await import_csv(TEST_DATABASE_URL, SAMPLE)
    assert changed == 0
    go_id = go.id
    await db_session.execute(update(Word).where(Word.id == go_id).values(translation="stale"))
    await db_session.execute(update(Word).where(Word.word == "the").values(word="the-old-spelling"))
    await db_session.commit()

    # A changed row is refreshed; a word no longer in the file is kept (cards use it).
    _, changed = await import_csv(TEST_DATABASE_URL, SAMPLE)
    assert changed == 2
    db_session.expire_all()
    go = await db_session.scalar(select(Word).where(Word.word == "go"))
    assert go is not None and go.id == go_id and go.translation != "stale"
    assert await db_session.scalar(select(Word).where(Word.word == "the-old-spelling"))


async def test_download_checks_the_pinned_file(tmp_path: Path) -> None:
    body = b"word,phonetic\n"
    good = hashlib.sha256(body).hexdigest()
    requests: list[str] = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        requests.append(str(request.url))
        return httpx2.Response(200, content=body)

    transport = httpx2.MockTransport(serve)
    dest = tmp_path / "data" / "ecdict.csv"
    assert await download("https://mirror.test/e.csv", dest, good, transport=transport) == dest
    assert dest.read_bytes() == body
    # Cached: no second request.
    await download("https://mirror.test/e.csv", dest, good, transport=transport)
    assert len(requests) == 1

    with pytest.raises(DownloadError, match="sha256"):
        await download(
            "https://mirror.test/e.csv", tmp_path / "x.csv", "0" * 64, transport=transport
        )
    assert [p async for p in anyio.Path(tmp_path).glob("x.*")] == []

    missing = httpx2.MockTransport(lambda _: httpx2.Response(404))
    with pytest.raises(DownloadError, match="HTTP 404"):
        await download("https://mirror.test/e.csv", tmp_path / "y.csv", good, transport=missing)
