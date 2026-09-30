import base64
import io
import uuid
from typing import Any

import httpx2
import openai
import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service
from app.credentials.crypto import generate_key_entry, get_keyring, parse_keyring
from app.credentials.rotate import rotate_credentials
from app.db.models import ProviderConnection
from app.providers import asr, net_guard
from app.providers.model_catalog import DiscoveredModel, ModelListError
from app.providers.net_guard import IPAddress
from app.providers.tenant import load_provider_context

SECRET = "sk-live-abcdefghijklmnop"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hostnames resolve to a public address; IP literals resolve to themselves."""
    import ipaddress

    async def fake_resolve(host: str, port: int) -> list[IPAddress]:
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(net_guard, "resolve", fake_resolve)


@pytest.fixture(autouse=True)
def fresh_model_cache() -> None:
    service.reset_model_cache()


async def login(client: AsyncClient, email: str = "owner@example.com") -> None:
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201


async def create(client: AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/tenant/connections", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


async def test_endpoints_require_login(client: AsyncClient) -> None:
    for method, path in [("GET", "/tenant/connections"), ("GET", "/provider-presets")]:
        assert (await client.request(method, path)).status_code == 401


async def test_presets_listed(client: AsyncClient) -> None:
    await login(client)
    body = (await client.get("/provider-presets")).json()
    names = {p["name"] for p in body["presets"]}
    assert {"deepseek", "anthropic", "openai"} <= names
    assert body["allow_private_networks"] is False


async def test_create_from_preset_never_returns_the_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    data = await create(client, preset="deepseek", api_key=SECRET)
    assert data["name"] == "deepseek"
    assert data["kind"] == "deepseek"
    assert data["base_url"] == "https://api.deepseek.com/v1"
    assert data["has_api_key"] is True and data["key_hint"] == "…mnop"
    listing = await client.get("/tenant/connections")
    assert SECRET not in listing.text and SECRET not in str(data)

    row = await db_session.scalar(select(ProviderConnection))
    assert row is not None and row.encrypted_api_key is not None
    assert SECRET not in row.encrypted_api_key  # stored encrypted


async def test_custom_anthropic_relay_endpoint(client: AsyncClient) -> None:
    await login(client)
    data = await create(
        client,
        preset="anthropic",
        name="claude-relay",
        base_url="https://relay.example.com/",
        api_key=SECRET,
    )
    assert (data["name"], data["kind"], data["base_url"]) == (
        "claude-relay",
        "anthropic",
        "https://relay.example.com",
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"preset": "deepseek"}, "need an API key"),
        ({"preset": "nope", "api_key": SECRET}, "unknown preset"),
        ({"preset": "openai", "api_key": SECRET, "base_url": "http://api.example.com"}, "https"),
        ({"preset": "openai", "api_key": SECRET, "base_url": "https://10.0.0.1/v1"}, "non-public"),
        ({"preset": "openai", "api_key": SECRET, "name": "Bad Name"}, "connection name"),
        ({"kind": "openai", "api_key": SECRET}, "name and base_url are required"),
    ],
)
async def test_invalid_connections_rejected(
    client: AsyncClient, body: dict[str, Any], message: str
) -> None:
    await login(client)
    response = await client.post("/tenant/connections", json=body)
    assert response.status_code == 422
    assert message in response.text


@pytest.mark.parametrize(
    "params",
    [{"http_async_client": "x"}, {"default_headers": {"x": "y"}}, {"openai_proxy": "http://p"}],
)
async def test_params_outside_allow_list_rejected(
    client: AsyncClient, params: dict[str, Any]
) -> None:
    """Arbitrary SDK kwargs could bypass the SSRF guard; only the allow-list gets through."""
    await login(client)
    response = await client.post(
        "/tenant/connections", json={"preset": "openai", "api_key": SECRET, "params": params}
    )
    assert response.status_code == 422


async def test_duplicate_name_conflicts(client: AsyncClient) -> None:
    await login(client)
    await create(client, preset="openai", api_key=SECRET)
    response = await client.post(
        "/tenant/connections", json={"preset": "openai", "api_key": SECRET}
    )
    assert response.status_code == 409


async def test_update_rotates_key_and_resets_verification(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conn = await create(client, preset="openai", api_key=SECRET)
    row = await db_session.get(ProviderConnection, uuid.UUID(conn["id"]))
    assert row is not None
    row.last_error = "old failure"
    await db_session.commit()

    response = await client.patch(
        f"/tenant/connections/{conn['id']}",
        json={"api_key": "sk-new-key-0000000000", "params": {"temperature": 0.3}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key_hint"] == "…0000" and data["params"] == {"temperature": 0.3}
    assert data["last_error"] is None


async def test_other_tenants_connections_are_invisible(client: AsyncClient) -> None:
    await login(client, "a@example.com")
    conn = await create(client, preset="openai", api_key=SECRET)
    client.cookies.clear()
    await login(client, "b@example.com")
    assert (await client.get("/tenant/connections")).json() == []
    assert (await client.delete(f"/tenant/connections/{conn['id']}")).status_code == 404
    patch = await client.patch(f"/tenant/connections/{conn['id']}", json={"enabled": False})
    assert patch.status_code == 404


async def test_delete_connection(client: AsyncClient) -> None:
    await login(client)
    conn = await create(client, preset="openai", api_key=SECRET)
    assert (await client.delete(f"/tenant/connections/{conn['id']}")).status_code == 204
    assert (await client.get("/tenant/connections")).json() == []


async def test_verify_connection_records_result(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client)
    conn = await create(client, preset="openai", api_key=SECRET)

    class FakeModel:
        def __init__(self, fail: bool) -> None:
            self.fail = fail

        async def ainvoke(self, _: Any) -> AIMessage:
            if self.fail:
                raise RuntimeError("401 invalid api key")
            return AIMessage("OK")

    outcomes = iter([True, False])
    recorders: list[Any] = []

    def fake_build(r: Any, task: str, *, callbacks: list[Any]) -> FakeModel:
        recorders.extend(callbacks)
        return FakeModel(next(outcomes))

    monkeypatch.setattr(service, "build_chat_model", fake_build)

    failed = (
        await client.post(f"/tenant/connections/{conn['id']}/test", json={"model": "m"})
    ).json()
    assert failed["ok"] is False and "invalid api key" in failed["error"]
    ok = (await client.post(f"/tenant/connections/{conn['id']}/test", json={"model": "m"})).json()
    assert ok["ok"] is True
    listed = (await client.get("/tenant/connections")).json()[0]
    assert listed["last_verified_at"] is not None and listed["last_error"] is None
    # Test calls hit the tenant's real account, so they are metered like any other call.
    assert [(r.labels.task, r.labels.connection, r.labels.model) for r in recorders] == [
        ("connection_test", conn["name"], "m")
    ] * 2


def serve_transcriptions(
    monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, Any]
) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    def fake_client(model: Any) -> AsyncOpenAI:
        transport = httpx2.MockTransport(handle)
        return AsyncOpenAI(
            api_key="k",
            base_url=model.base_url,
            http_client=httpx2.AsyncClient(transport=transport),
        )

    monkeypatch.setattr(asr, "_client", fake_client)
    return seen


async def test_speech_model_is_tested_by_transcribing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = serve_transcriptions(monkeypatch, 200, {"text": ""})
    await login(client)
    conn = await create(
        client, name="local", kind="openai_compatible", base_url="https://stt.example.com/v1"
    )
    url = f"/tenant/connections/{conn['id']}/test"

    result = (await client.post(url, json={"model": "Systran/faster-whisper-small"})).json()

    assert (result["ok"], result["purpose"], result["error_code"]) == (True, "asr", None)
    (request,) = seen
    assert request.url.path == "/v1/audio/transcriptions"
    assert b"RIFF" in request.read()  # the built-in WAV clip


async def test_relay_without_transcriptions_is_reported_as_such(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve_transcriptions(monkeypatch, 404, {"error": {"message": "Invalid URL"}})
    await login(client)
    conn = await create(
        client, name="relay", kind="openai_compatible", base_url="https://relay.example.com/v1"
    )
    url = f"/tenant/connections/{conn['id']}/test"

    result = (await client.post(url, json={"model": "whisper-1"})).json()

    assert (result["ok"], result["purpose"]) == (False, "asr")
    assert result["error_code"] == "asr_not_supported"
    assert result["error"].startswith("NotFoundError")
    listed = (await client.get("/tenant/connections")).json()[0]
    assert listed["last_error"] == result["error"]


async def test_model_on_the_speech_route_is_tested_by_transcribing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = serve_transcriptions(monkeypatch, 200, {"text": ""})
    chats: list[str] = []

    class FakeModel:
        async def ainvoke(self, _: Any) -> AIMessage:
            return AIMessage("OK")

    def fake_build(r: Any, task: str, *, callbacks: list[Any]) -> FakeModel:
        chats.append(r.model)
        return FakeModel()

    monkeypatch.setattr(service, "build_chat_model", fake_build)
    await login(client)
    conn = await create(
        client, name="local", kind="openai_compatible", base_url="https://stt.example.com/v1"
    )
    url = f"/tenant/connections/{conn['id']}/test"
    # Nothing in the name says speech-to-text: tested as chat until the route uses it.
    assert (await client.post(url, json={"model": "my-stt"})).json()["purpose"] == "chat"
    put = await client.put("/tenant/routes/asr/default", json={"models": ["local:my-stt"]})
    assert put.status_code == 200

    assert (await client.post(url, json={"model": "my-stt"})).json()["purpose"] == "asr"
    # An explicit purpose wins over the guess.
    explicit = {"model": "my-stt", "purpose": "chat"}
    assert (await client.post(url, json=explicit)).json()["purpose"] == "chat"
    assert chats == ["my-stt", "my-stt"] and len(seen) == 1


def bad_request() -> httpx2.Response:
    return httpx2.Response(400, request=httpx2.Request("POST", "https://relay.example.com/v1"))


async def test_vision_test_sends_an_image(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []
    outcomes = iter([None, openai.BadRequestError("no images", response=bad_request(), body=None)])

    class FakeModel:
        async def ainvoke(self, messages: Any) -> AIMessage:
            sent.append(messages)
            if (error := next(outcomes)) is not None:
                raise error
            return AIMessage("Red")

    monkeypatch.setattr(service, "build_chat_model", lambda *a, **k: FakeModel())
    await login(client)
    conn = await create(
        client, name="relay", kind="openai_compatible", base_url="https://relay.example.com/v1"
    )
    url = f"/tenant/connections/{conn['id']}/test"
    # On the vision route: guessed as vision. An explicit purpose tests any model.
    put = await client.put("/tenant/routes/llm/vision", json={"models": ["relay:eyes"]})
    assert put.status_code == 200

    ok = (await client.post(url, json={"model": "eyes"})).json()
    refused = (await client.post(url, json={"model": "blind", "purpose": "vision"})).json()

    assert (ok["ok"], ok["purpose"]) == (True, "vision")
    (message,) = sent[0]
    image = message.content[1]
    assert image["mime_type"] == "image/png"
    assert base64.b64decode(image["base64"]).startswith(b"\x89PNG")
    assert (refused["ok"], refused["purpose"]) == (False, "vision")
    assert refused["error_code"] == "vision_not_supported"


def test_built_in_test_image_is_a_valid_png() -> None:
    from PIL import Image

    with Image.open(io.BytesIO(service.test_image())) as image:
        assert (image.format, image.size, image.getpixel((5, 5))) == ("PNG", (32, 32), (255, 0, 0))


async def test_anthropic_is_always_tested_as_chat(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeModel:
        async def ainvoke(self, _: Any) -> AIMessage:
            return AIMessage("OK")

    monkeypatch.setattr(service, "build_chat_model", lambda *a, **k: FakeModel())
    await login(client)
    conn = await create(client, preset="anthropic", api_key=SECRET)
    url = f"/tenant/connections/{conn['id']}/test"
    assert (await client.post(url, json={"model": "whisper-lookalike"})).json()["purpose"] == "chat"


# --- routes -----------------------------------------------------------------------------


async def test_routes_default_then_override_then_revert(client: AsyncClient) -> None:
    await login(client)
    await create(client, preset="openai", api_key=SECRET)
    await create(
        client, preset="anthropic", name="relay", base_url="https://r.example.com", api_key=SECRET
    )

    def chat(routes: list[dict[str, Any]]) -> dict[str, Any]:
        return next(r for r in routes if r["section"] == "llm" and r["task"] == "chat")

    assert chat((await client.get("/tenant/routes")).json())["overridden"] is False

    put = await client.put(
        "/tenant/routes/llm/chat",
        json={
            "models": ["relay:claude-sonnet-5", "openai:gpt-5-mini"],
            "params": {"temperature": 0.2},
        },
    )
    assert put.status_code == 200
    route = chat((await client.get("/tenant/routes")).json())
    assert route["overridden"] is True
    assert route["models"] == ["relay:claude-sonnet-5", "openai:gpt-5-mini"]

    assert (await client.delete("/tenant/routes/llm/chat")).status_code == 204
    assert chat((await client.get("/tenant/routes")).json())["overridden"] is False


@pytest.mark.parametrize(
    ("path", "body", "message"),
    [
        ("/tenant/routes/llm/no-such-task", {"models": ["openai:m"]}, "unknown llm task"),
        ("/tenant/routes/llm/chat", {"models": ["ghost:m"]}, "no connection named 'ghost'"),
        ("/tenant/routes/llm/chat", {"models": ["openai"]}, "<connection>:<model>"),
        ("/tenant/routes/embedding/default", {"models": ["openai:a", "openai:b"]}, "exactly one"),
    ],
)
async def test_invalid_routes_rejected(
    client: AsyncClient, path: str, body: dict[str, Any], message: str
) -> None:
    await login(client)
    await create(client, preset="openai", api_key=SECRET)
    response = await client.put(path, json=body)
    assert response.status_code == 422
    assert message in response.text


# --- end to end: API writes -> provider context ------------------------------------------


async def test_saved_settings_drive_the_provider_context(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    await create(client, preset="deepseek", api_key=SECRET, params={"timeout": 45})
    await client.put("/tenant/routes/llm/chat", json={"models": ["deepseek:deepseek-chat"]})
    me = (await client.get("/auth/me")).json()

    ctx = await load_provider_context(db_session, uuid.UUID(me["tenant"]["id"]))
    deepseek = ctx.connections["deepseek"]
    assert deepseek.api_key is not None and deepseek.api_key.get_secret_value() == SECRET
    assert deepseek.params == {"timeout": 45}
    assert ctx.routes[("llm", "chat")].models == ["deepseek:deepseek-chat"]


async def test_key_rotation(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    await create(client, preset="openai", api_key=SECRET)
    old = get_keyring()
    new_entry = generate_key_entry("next")
    old_entry = (
        f"{old.primary_id}:"
        + __import__("base64").urlsafe_b64encode(old.keys[old.primary_id]).decode()
    )
    rotating = parse_keyring(f"{new_entry},{old_entry}")

    assert await rotate_credentials(db_session, rotating) == 1
    assert await rotate_credentials(db_session, rotating) == 0  # idempotent

    row = await db_session.scalar(select(ProviderConnection))
    assert row is not None and row.encrypted_api_key is not None
    assert row.encrypted_api_key.startswith("v1:next:")
    only_new = parse_keyring(new_entry)
    ctx = await load_provider_context(db_session, row.tenant_id, keyring=only_new)
    key = ctx.connections["openai"].api_key
    assert key is not None and key.get_secret_value() == SECRET


async def test_list_models_is_cached_until_the_connection_changes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def fake_fetch(
        kind: str, base_url: str, api_key: Any, *, client: Any
    ) -> list[DiscoveredModel]:
        calls.append((kind, base_url, api_key.get_secret_value() if api_key else None))
        return [
            DiscoveredModel("gpt-5-mini", "chat"),
            DiscoveredModel("text-embedding-3-small", "embedding"),
        ]

    monkeypatch.setattr(service, "fetch_models", fake_fetch)
    await login(client)
    conn = await create(client, preset="openai", api_key=SECRET)
    url = f"/tenant/connections/{conn['id']}/models"

    first = await client.get(url)
    assert first.status_code == 200
    assert first.json() == {
        "models": [
            {"id": "gpt-5-mini", "category": "chat"},
            {"id": "text-embedding-3-small", "category": "embedding"},
        ]
    }
    await client.get(url)
    assert calls == [("openai", "https://api.openai.com/v1", SECRET)]  # decrypted key, one call

    await client.patch(
        f"/tenant/connections/{conn['id']}", json={"api_key": "sk-new-key-0000000000"}
    )
    await client.get(url)
    assert len(calls) == 2 and calls[1][2] == "sk-new-key-0000000000"


async def test_list_models_vendor_failure_is_a_502_with_the_reason(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_fetch(*args: Any, **kwargs: Any) -> list[DiscoveredModel]:
        raise ModelListError("HTTP 401: Incorrect API key provided")

    monkeypatch.setattr(service, "fetch_models", failing_fetch)
    await login(client)
    conn = await create(client, preset="openai", api_key=SECRET)
    response = await client.get(f"/tenant/connections/{conn['id']}/models")
    assert response.status_code == 502
    assert response.json() == {
        "detail": {"code": "model_list_failed", "message": "HTTP 401: Incorrect API key provided"}
    }


async def test_list_models_of_another_tenant_is_404(client: AsyncClient) -> None:
    await login(client, "a@example.com")
    conn = await create(client, preset="openai", api_key=SECRET)
    client.cookies.clear()
    await login(client, "b@example.com")
    response = await client.get(f"/tenant/connections/{conn['id']}/models")
    assert response.status_code == 404


# --- default models and the auto fallback (ADR 0007) ------------------------------------


async def test_default_model_from_preset_request_and_patch(client: AsyncClient) -> None:
    await login(client)
    preset = await create(client, preset="openai", api_key=SECRET)
    assert preset["default_model"] == "gpt-5-mini"  # the preset's first chat model

    relay = await create(
        client,
        name="relay",
        kind="openai_compatible",
        base_url="https://relay.example.com/v1",
        api_key=SECRET,
        default_model=" some-model ",
    )
    assert relay["default_model"] == "some-model"

    url = f"/tenant/connections/{relay['id']}"
    assert (await client.patch(url, json={"default_model": "other"})).json()[
        "default_model"
    ] == "other"
    assert (await client.patch(url, json={"enabled": True})).json()["default_model"] == "other"
    assert (await client.patch(url, json={"default_model": ""})).json()["default_model"] is None


async def test_test_uses_the_default_model_unless_one_is_given(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tested: list[str] = []

    class FakeModel:
        async def ainvoke(self, _: Any) -> AIMessage:
            return AIMessage("OK")

    def fake_build(r: Any, task: str, *, callbacks: list[Any]) -> FakeModel:
        tested.append(r.model)
        return FakeModel()

    monkeypatch.setattr(service, "build_chat_model", fake_build)
    await login(client)
    conn = await create(
        client,
        name="relay",
        kind="openai_compatible",
        base_url="https://relay.example.com/v1",
        default_model="relay-default",
    )
    url = f"/tenant/connections/{conn['id']}/test"
    assert (await client.post(url, json={})).json()["ok"] is True
    assert (await client.post(url, json={"model": "explicit"})).json()["ok"] is True
    assert tested == ["relay-default", "explicit"]

    await client.patch(f"/tenant/connections/{conn['id']}", json={"default_model": ""})
    response = await client.post(url, json={})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_provider_config"


async def test_routes_report_what_actually_runs(client: AsyncClient) -> None:
    def chat(routes: list[dict[str, Any]]) -> dict[str, Any]:
        return next(r for r in routes if r["section"] == "llm" and r["task"] == "chat")

    await login(client)
    nothing = chat((await client.get("/tenant/routes")).json())
    assert (nothing["effective"], nothing["effective_source"]) == ([], None)

    # A relay whose name matches no default route still works, via its default model.
    await create(
        client,
        name="dd",
        kind="openai_compatible",
        base_url="https://relay.example.com/v1",
        api_key=SECRET,
        default_model="relay-model",
    )
    auto = chat((await client.get("/tenant/routes")).json())
    assert (auto["effective"], auto["effective_source"]) == (["dd:relay-model"], "auto")
    assert auto["overridden"] is False

    # A preset connection makes the YAML route match again, as written.
    await create(client, preset="openai", api_key=SECRET)
    default = chat((await client.get("/tenant/routes")).json())
    assert (default["effective"], default["effective_source"]) == (["openai:gpt-5-mini"], "default")

    put = await client.put("/tenant/routes/llm/chat", json={"models": ["dd:x", "openai:y"]})
    assert (put.json()["effective"], put.json()["effective_source"]) == (
        ["dd:x", "openai:y"],
        "override",
    )


async def test_provider_context_keeps_creation_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    for name in ("zeta", "alpha", "mid"):
        await create(
            client,
            name=name,
            kind="openai_compatible",
            base_url=f"https://{name}.example.com/v1",
            default_model=f"{name}-model",
        )
    row = await db_session.scalar(select(ProviderConnection))
    assert row is not None
    ctx = await load_provider_context(db_session, row.tenant_id, get_keyring())
    assert list(ctx.connections) == ["zeta", "alpha", "mid"]
    assert ctx.connections["alpha"].default_model == "alpha-model"


# --- editing every field (ADR 0007 §4) ---------------------------------------------------


def _chat_route(routes: list[dict[str, Any]]) -> dict[str, Any]:
    return next(r for r in routes if r["section"] == "llm" and r["task"] == "chat")


async def test_rename_rewrites_route_overrides_and_keeps_the_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    relay = await create(
        client,
        name="dd",
        kind="openai_compatible",
        base_url="https://relay.example.com/v1",
        api_key=SECRET,
        default_model="m",
    )
    other = await create(client, preset="openai", api_key=SECRET)
    put = await client.put(
        "/tenant/routes/llm/chat", json={"models": ["dd:a", "openai:b", "dd:c:free"]}
    )
    assert put.status_code == 200
    row = await db_session.get(ProviderConnection, uuid.UUID(relay["id"]))
    assert row is not None
    row.last_verified_at = row.created_at
    await db_session.commit()

    response = await client.patch(f"/tenant/connections/{relay['id']}", json={"name": "relay"})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "relay"
    assert response.json()["last_verified_at"] is None
    route = _chat_route((await client.get("/tenant/routes")).json())
    assert route["models"] == ["relay:a", "openai:b", "relay:c:free"]
    assert route["effective"] == ["relay:a", "openai:b", "relay:c:free"]

    # The key is bound to the connection id, not its name: it still decrypts.
    tenant_id = row.tenant_id
    db_session.expire_all()
    ctx = await load_provider_context(db_session, tenant_id)
    assert ctx.connections["relay"].api_key is not None
    assert ctx.connections["relay"].api_key.get_secret_value() == SECRET
    assert "dd" not in ctx.connections and "openai" in ctx.connections
    assert other["name"] == "openai"


async def test_rename_to_a_taken_or_invalid_name_changes_nothing(client: AsyncClient) -> None:
    await login(client)
    relay = await create(
        client, name="dd", kind="openai_compatible", base_url="https://relay.example.com/v1"
    )
    await create(client, preset="openai", api_key=SECRET)
    await client.put("/tenant/routes/llm/chat", json={"models": ["dd:a"]})
    url = f"/tenant/connections/{relay['id']}"

    taken = await client.patch(url, json={"name": "openai", "base_url": "https://x.example.com"})
    assert taken.status_code == 409
    assert taken.json()["detail"]["code"] == "connection_name_taken"
    bad = await client.patch(url, json={"name": "Bad Name"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_provider_config"

    [conn] = [c for c in (await client.get("/tenant/connections")).json() if c["id"] == relay["id"]]
    assert (conn["name"], conn["base_url"]) == ("dd", "https://relay.example.com/v1")
    assert _chat_route((await client.get("/tenant/routes")).json())["models"] == ["dd:a"]


async def test_change_kind_needs_a_key_for_official_apis(client: AsyncClient) -> None:
    await login(client)
    keyless = await create(
        client, name="local", kind="openai_compatible", base_url="https://llm.example.com/v1"
    )
    url = f"/tenant/connections/{keyless['id']}"

    refused = await client.patch(url, json={"kind": "openai"})
    assert refused.status_code == 422
    assert "need an API key" in refused.json()["detail"]["message"]
    bogus = await client.patch(url, json={"kind": "nope"})
    assert bogus.status_code == 422

    # Switching kind and supplying the key together is fine.
    ok = await client.patch(url, json={"kind": "openai", "api_key": SECRET})
    assert ok.status_code == 200, ok.text
    assert (ok.json()["kind"], ok.json()["has_api_key"]) == ("openai", True)
    back = await client.patch(url, json={"kind": "openai_compatible"})
    assert back.json()["kind"] == "openai_compatible"


def _route(routes: list[dict[str, Any]], section: str, task: str) -> dict[str, Any]:
    return next(r for r in routes if (r["section"], r["task"]) == (section, task))


async def test_vision_and_speech_routes_are_listed_and_never_guessed(client: AsyncClient) -> None:
    await login(client)
    # A chat-only relay: chat falls back to its default model (ADR 0007), but vision and
    # speech-to-text must stay unconfigured rather than guess (ADR 0008 §5).
    await create(
        client,
        name="relay",
        kind="openai_compatible",
        base_url="https://relay.example.com/v1",
        api_key="sk-relay",
        default_model="chat-model",
    )

    routes = (await client.get("/tenant/routes")).json()

    assert _route(routes, "llm", "chat")["effective"] == ["relay:chat-model"]
    for section, task in (("llm", "vision"), ("asr", "default")):
        route = _route(routes, section, task)
        assert (route["effective"], route["effective_source"]) == ([], None)

    response = await client.put("/tenant/routes/llm/vision", json={"models": ["relay:qwen-vl-max"]})
    assert response.status_code == 200, response.text
    assert response.json()["effective"] == ["relay:qwen-vl-max"]
    response = await client.put("/tenant/routes/asr/default", json={"models": ["relay:whisper-1"]})
    assert response.status_code == 200, response.text
    assert response.json()["effective_source"] == "override"


async def test_speech_routes_need_a_transcription_api(client: AsyncClient) -> None:
    await login(client)
    await create(client, preset="deepseek", api_key="sk-deepseek")

    response = await client.put(
        "/tenant/routes/asr/default", json={"models": ["deepseek:deepseek-chat"]}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_provider_config"
    assert "speech-to-text" in response.json()["detail"]["message"]
