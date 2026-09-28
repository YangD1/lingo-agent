from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_engine, create_sessionmaker
from app.main import create_app


def _client_for(engine: AsyncEngine) -> AsyncClient:
    app = create_app()
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def unreachable_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine("postgresql+psycopg://nobody:x@127.0.0.1:1/none_test")
    yield engine
    await engine.dispose()


async def test_healthz() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_ok(db_engine: AsyncEngine) -> None:
    async with _client_for(db_engine) as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_readyz_reports_unreachable_database(unreachable_engine: AsyncEngine) -> None:
    async with _client_for(unreachable_engine) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"
