from typing import Any

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TtsAudio
from app.providers import net_guard, tts
from app.providers.net_guard import IPAddress
from app.services.speech import read_aloud


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    import ipaddress

    async def fake_resolve(host: str, port: int) -> list[IPAddress]:
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(net_guard, "resolve", fake_resolve)


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A fake speech vendor: answers by host, records what it was asked."""

    class Vendor:
        def __init__(self) -> None:
            self.seen: list[httpx2.Request] = []
            self.status: dict[str, int] = {}

        def handle(self, request: httpx2.Request) -> httpx2.Response:
            self.seen.append(request)
            code = self.status.get(request.url.host, 200)
            body = f"mp3:{request.url.host}:{len(self.seen)}".encode() if code == 200 else b"no"
            return httpx2.Response(code, content=body)

    fake = Vendor()

    def client(*, allow_private: bool, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle))

    monkeypatch.setattr(tts, "make_async_http_client", client)
    return fake


async def setup(client: AsyncClient, email: str = "a@example.com") -> None:
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    for name, host in (("one", "one.example.com"), ("two", "two.example.com")):
        response = await client.post(
            "/tenant/connections",
            json={
                "name": name,
                "kind": "openai_compatible",
                "base_url": f"https://{host}/v1",
                "api_key": "sk-test-0123456789",
            },
        )
        assert response.status_code == 201, response.text
    response = await client.put(
        "/tenant/routes/tts/default", json={"models": ["one:tts-1", "two:tts-1"]}
    )
    assert response.status_code == 200, response.text


def say(text: str = "Nice to meet you.", **extra: Any) -> dict[str, Any]:
    return {"text": text, "language": "en-US", "speed": 0.9, **extra}


async def test_without_a_route_the_browser_reads_aloud(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": "a@example.com", "password": "password123"})

    assert (await client.get("/speech/capabilities")).json() == {"tts": False, "tts_languages": []}
    response = await client.post("/speech/tts", json=say())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_tts_model"


async def test_second_request_is_served_from_the_cache(
    client: AsyncClient, vendor: Any, db_session: AsyncSession
) -> None:
    await setup(client)
    assert (await client.get("/speech/capabilities")).json() == {
        "tts": True,
        "tts_languages": ["en-US", "en-GB", "zh-CN"],
    }

    first = await client.post("/speech/tts", json=say("  Nice to meet you. "))
    second = await client.post("/speech/tts", json=say())

    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "audio/mpeg"
    assert (first.headers["x-tts-cached"], second.headers["x-tts-cached"]) == ("0", "1")
    assert first.content == second.content == b"mp3:one.example.com:1"
    assert len(vendor.seen) == 1
    # A different speed is different audio.
    third = await client.post("/speech/tts", json=say(speed=1.1))
    assert third.headers["x-tts-cached"] == "0"
    assert await db_session.scalar(select(func.count()).select_from(TtsAudio)) == 2


async def test_a_fallbacks_audio_is_reused(client: AsyncClient, vendor: Any) -> None:
    await setup(client)
    vendor.status["one.example.com"] = 503

    first = await client.post("/speech/tts", json=say())
    vendor.status.clear()  # the primary is back, but the sentence is already paid for
    second = await client.post("/speech/tts", json=say())

    assert first.content == second.content == b"mp3:two.example.com:2"
    assert second.headers["x-tts-cached"] == "1"
    assert len(vendor.seen) == 2


async def test_a_language_without_a_voice_is_left_to_the_browser(
    client: AsyncClient, vendor: Any
) -> None:
    await setup(client)
    route = {"models": ["one:speaches-ai/Kokoro-82M-v1.0-ONNX"]}
    assert (await client.put("/tenant/routes/tts/default", json=route)).status_code == 200

    capabilities = (await client.get("/speech/capabilities")).json()
    response = await client.post("/speech/tts", json={"text": "你好", "language": "zh-CN"})

    assert capabilities == {"tts": True, "tts_languages": ["en-US", "en-GB"]}
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_tts_voice"
    assert vendor.seen == []


async def test_route_shows_built_in_voices_and_keeps_chosen_ones(
    client: AsyncClient, vendor: Any
) -> None:
    await setup(client)
    kokoro = "one:speaches-ai/Kokoro-82M-v1.0-ONNX"
    route = {
        "models": [kokoro, "two:tts-1"],
        "params": {"voices": {kokoro: {"en-US": "am_adam"}}},
    }
    saved = (await client.put("/tenant/routes/tts/default", json=route)).json()

    assert saved["params"] == {"voices": {kokoro: {"en-US": "am_adam"}}}
    assert saved["default_voices"] == {
        kokoro: {"en-US": "af_heart", "en-GB": "bf_emma", "zh-CN": None},
        "two:tts-1": {"en-US": "coral", "en-GB": "coral", "zh-CN": "coral"},
    }
    routes = (await client.get("/tenant/routes")).json()
    chat = next(r for r in routes if r["section"] == "llm" and r["task"] == "chat")
    assert chat["default_voices"] is None
    await client.post("/speech/tts", json=say())
    assert b'"voice":"am_adam"' in vendor.seen[0].content.replace(b" ", b"")


async def test_every_model_failing_is_a_502(client: AsyncClient, vendor: Any) -> None:
    await setup(client)
    vendor.status.update({"one.example.com": 500, "two.example.com": 429})

    response = await client.post("/speech/tts", json=say())

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "tts_unavailable"


async def test_cache_is_per_tenant(client: AsyncClient, vendor: Any) -> None:
    await setup(client)
    await client.post("/speech/tts", json=say())
    client.cookies.clear()
    await setup(client, "b@example.com")

    response = await client.post("/speech/tts", json=say())

    assert response.headers["x-tts-cached"] == "0"
    assert len(vendor.seen) == 2


@pytest.mark.parametrize(
    "body",
    [
        say("   "),
        say("x" * 1001),
        say(language="fr-FR"),
        say(speed=3),
        say(voice="anything"),  # the route picks voices, not the learner
    ],
)
async def test_invalid_requests(client: AsyncClient, vendor: Any, body: dict[str, Any]) -> None:
    await setup(client)
    response = await client.post("/speech/tts", json=body)
    assert response.status_code == 422
    assert vendor.seen == []


async def test_eviction_drops_least_recently_used_unpinned_audio(db_session: AsyncSession) -> None:
    from app.db.models import Tenant

    tenant = Tenant(name="t", kind="personal")
    db_session.add(tenant)
    await db_session.flush()

    def row(key: str, size: int, minutes_ago: int, *, pinned: bool = False) -> TtsAudio:
        return TtsAudio(
            tenant_id=tenant.id,
            key=key,
            language="en-US",
            connection_name="c",
            model="m",
            voice="v",
            mime_type="audio/mpeg",
            audio=b"x" * size,
            size=size,
            pinned=pinned,
            last_used_at=func.now() - func.make_interval(0, 0, 0, 0, 0, minutes_ago),
        )

    db_session.add_all(
        [row("new", 40, 1), row("mid", 40, 2), row("old", 40, 3), row("word", 500, 9, pinned=True)]
    )
    await db_session.commit()

    await read_aloud.evict(db_session, tenant.id, max_bytes=100)
    await db_session.commit()

    keys = set(await db_session.scalars(select(TtsAudio.key)))
    assert keys == {"new", "mid", "word"}


def test_cache_key_depends_on_everything_that_changes_the_audio() -> None:
    from app.providers.config import ResolvedModel

    m = ResolvedModel("c", "openai", "tts-1", "https://x", None)
    base = read_aloud.cache_key("Hi", "en-US", "coral", 0.9, m)
    assert base == read_aloud.cache_key("Hi", "en-US", "coral", 0.9000001, m)
    others = {
        read_aloud.cache_key("Hi!", "en-US", "coral", 0.9, m),
        read_aloud.cache_key("Hi", "en-GB", "coral", 0.9, m),
        read_aloud.cache_key("Hi", "en-US", "alloy", 0.9, m),
        read_aloud.cache_key("Hi", "en-US", "coral", 1.0, m),
        read_aloud.cache_key(
            "Hi", "en-US", "coral", 0.9, ResolvedModel("d", "openai", "tts-1", "", None)
        ),
    }
    assert base not in others and len(others) == 5
