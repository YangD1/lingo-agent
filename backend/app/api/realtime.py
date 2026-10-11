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
from datetime import UTC, datetime
from functools import partial
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import InvalidTokenError, decode_access_token
from app.auth.service import get_personal_tenant
from app.db.models import User
from app.deps import AUTH_COOKIE, CurrentTenant, CurrentUser, Manager, SessionDep
from app.memory.embedding import memory_embedder
from app.memory.reflection import LOCALE_COOKIE
from app.providers.errors import NoModelConfiguredError
from app.providers.openai_realtime import RealtimeConnectError, RealtimeSession, open_session
from app.providers.realtime import RealtimeRoute, get_realtime
from app.providers.tenant import load_provider_context
from app.realtime import calls
from app.realtime.calls import RealtimeCalls
from app.realtime.context import call_instructions
from app.realtime.limits import CallLimit, LimitState, call_limit
from app.realtime.relay import TASK, CallInfo, RealtimeCall
from app.realtime.tools import SPECS as TOOL_SPECS
from app.realtime.tools import CallTools
from app.settings import get_settings
from app.speaking import sessions
from app.speaking.scenarios import get_scenarios
from app.usage.recorder import UsageRecord, submit_usage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speech"])

# Upper bounds an admin can set (ADR 0030 §5); the vendor bills by the minute.
MAX_SESSION_MINUTES = 60
MAX_DAILY_MINUTES = 600


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


@router.websocket("/speech/realtime")
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
        limit = await call_limit(session, tenant, user.id, datetime.now(UTC))
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
    registry: RealtimeCalls = websocket.app.state.realtime_calls
    if registry.has_user(user.id):
        # Two calls at once would each get today's minutes.
        await refuse("realtime_busy")
        return
    if limit.state != "ok":
        await refuse("realtime_off" if limit.state == "off" else "realtime_used_up")
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
            limit_seconds=limit.allowed_seconds,
            is_fallback=position > 0,
        ),
        maker,
        partial(calls.save_lines, maker, websocket.app.state.chat_graph, row.conversation_id),
        CallTools(maker, user.id),
    )
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
            return await open_session(target, instructions=instructions, tools=TOOL_SPECS), position
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


class RealtimeLimitsOut(BaseModel):
    session_minutes: int
    daily_minutes: int
    # The calling admin's own use today (UTC), like the learner sees it.
    used_minutes: float
    state: LimitState


class RealtimeLimitsIn(BaseModel):
    # 0 turns realtime calls off.
    session_minutes: int = Field(ge=0, le=MAX_SESSION_MINUTES)
    daily_minutes: int = Field(ge=0, le=MAX_DAILY_MINUTES)


def _limits_out(limit: CallLimit) -> RealtimeLimitsOut:
    return RealtimeLimitsOut(
        session_minutes=limit.session_minutes,
        daily_minutes=limit.daily_minutes,
        used_minutes=round(limit.used_seconds / 60, 1),
        state=limit.state,
    )


@router.get("/tenant/realtime", dependencies=[Manager])
async def tenant_realtime(
    user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> RealtimeLimitsOut:
    """One call's length and each learner's minutes per UTC day (ADR 0030 §5)."""
    return _limits_out(await call_limit(session, tenant, user.id, datetime.now(UTC)))


@router.put("/tenant/realtime", dependencies=[Manager])
async def set_tenant_realtime(
    body: RealtimeLimitsIn, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> RealtimeLimitsOut:
    tenant.realtime_session_minutes = body.session_minutes
    tenant.realtime_daily_minutes = body.daily_minutes
    await session.commit()
    return _limits_out(await call_limit(session, tenant, user.id, datetime.now(UTC)))
