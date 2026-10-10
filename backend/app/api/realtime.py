"""Realtime voice calls (ADR 0030): `WS /speech/realtime`, relayed by the backend.

The browser can't set headers on a WebSocket, so it signs in with the auth cookie; the
Origin header must match the host it was sent to, so another site can't open a call
with that cookie (cross-site WebSocket hijacking). Errors before the call starts are
sent as one `ended` event with a `code`, since a browser can't read why a handshake
failed. The protocol itself is in `app/realtime/relay.py`.
"""

import json
import logging
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import InvalidTokenError, decode_access_token
from app.auth.service import get_personal_tenant
from app.db.models import User
from app.deps import AUTH_COOKIE
from app.memory.embedding import memory_embedder
from app.memory.reflection import LOCALE_COOKIE
from app.providers.errors import NoModelConfiguredError
from app.providers.openai_realtime import RealtimeConnectError, RealtimeSession, open_session
from app.providers.realtime import RealtimeRoute, get_realtime
from app.providers.tenant import load_provider_context
from app.realtime.calls import RealtimeCalls
from app.realtime.context import call_instructions
from app.realtime.relay import TASK, CallInfo, RealtimeCall
from app.settings import get_settings
from app.speaking import sessions
from app.speaking.scenarios import get_scenarios
from app.usage.recorder import UsageRecord, submit_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/speech", tags=["speech"])

# One call's length until task 60.5 reads the tenant's limits (ADR 0030 §5).
DEFAULT_LIMIT_SECONDS = 15 * 60


class _Browser:
    """The relay's BrowserSocket over a Starlette WebSocket."""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket

    async def receive(self) -> bytes | str | None:
        try:
            message = await self._ws.receive()
        except (WebSocketDisconnect, RuntimeError):
            return None
        if message["type"] == "websocket.disconnect":
            return None
        data = message.get("bytes")
        return data if data is not None else message.get("text")

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)

    async def send_json(self, data: dict[str, Any]) -> None:
        await self._ws.send_text(json.dumps(data))

    async def close(self) -> None:
        await self._ws.close()


def same_origin(websocket: WebSocket) -> bool:
    """No Origin: not a browser, so no ambient cookie to abuse. Otherwise it must name
    the host the request was sent to (or, behind the frontend's proxy, forwarded for)."""
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    netloc = urlsplit(origin).netloc.lower()
    hosts = [websocket.headers.get("host", "")]
    hosts += websocket.headers.get("x-forwarded-host", "").split(",")
    return bool(netloc) and netloc in {h.strip().lower() for h in hosts if h.strip()}


async def _user(websocket: WebSocket, session: AsyncSession) -> User | None:
    token = websocket.cookies.get(AUTH_COOKIE)
    bearer = websocket.headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        token = bearer[7:].strip()
    if not token:
        return None
    try:
        user_id = decode_access_token(token, get_settings())
    except InvalidTokenError:
        return None
    user = await session.get(User, user_id)
    return user if user is not None and user.is_active else None


@router.websocket("/realtime")
async def realtime_call(websocket: WebSocket, scenario: str | None = None) -> None:
    if not same_origin(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    maker: async_sessionmaker[AsyncSession] = websocket.app.state.sessionmaker
    async with maker() as session:
        user = await _user(websocket, session)
        tenant = await get_personal_tenant(session, user.id) if user is not None else None
        if user is None or tenant is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        ctx = await load_provider_context(session, tenant.id)
    await websocket.accept()
    browser = _Browser(websocket)

    async def refuse(code: str) -> None:
        await browser.send_json({"type": "ended", "reason": "refused", "code": code})
        await browser.close()

    try:
        route = get_realtime(ctx)
    except NoModelConfiguredError as exc:
        await refuse(exc.code)
        return
    found = get_scenarios().get(scenario) if scenario is not None else None
    if scenario is not None and found is None:
        await refuse("unknown_scenario")
        return
    instructions = await call_instructions(maker, user.id, found, memory_embedder(ctx))
    connected = await _connect(route, instructions, user.id)
    if connected is None:
        await refuse("realtime_unavailable")
        return
    vendor, position = connected
    async with maker() as session:
        row = await sessions.start(
            session,
            tenant.id,
            user.id,
            scenario,
            locale=websocket.cookies.get(LOCALE_COOKIE),
            mode="realtime",
        )
    call = RealtimeCall(
        browser,
        vendor,
        CallInfo(
            tenant_id=tenant.id,
            user_id=user.id,
            session_id=row.id,
            conversation_id=row.conversation_id,
            limit_seconds=DEFAULT_LIMIT_SECONDS,
            is_fallback=position > 0,
        ),
        maker,
    )
    registry: RealtimeCalls = websocket.app.state.realtime_calls
    registry.add(call)
    try:
        await call.run()
    finally:
        registry.done(call)


async def _connect(
    route: RealtimeRoute, instructions: str, user_id: uuid.UUID
) -> tuple[RealtimeSession, int] | None:
    """The first target in the route that takes the call (ADR 0030 §2: fallback only
    when connecting). Each failure is a usage row, like other calls'."""
    for position, target in enumerate(route.targets):
        started = time.monotonic()
        try:
            return await open_session(target, instructions=instructions), position
        except RealtimeConnectError as exc:
            cause = exc.__cause__ or exc
            logger.warning("realtime connect failed: %s", exc)
            submit_usage(
                UsageRecord(
                    tenant_id=route.tenant_id,
                    user_id=user_id,
                    conversation_id=None,
                    task=TASK,
                    connection_name=target.model.connection,
                    model=target.model.model,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    status="error",
                    is_fallback=position > 0,
                    error_code=type(cause).__name__[:64],
                )
            )
    return None
