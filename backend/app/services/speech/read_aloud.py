"""Server read-aloud with a per-tenant audio cache (ADR 0028 §3).

The same text in the same voice, speed and model is synthesized once per tenant; later
requests are served from `tts_audio` and cost nothing (no llm_usage row). The cache is
capped per tenant and evicts the least recently used audio first, except pinned rows.
A reply read aloud may say something personal (Q54c): each row keeps the learner who
first asked for it, who can clear their rows, and unpinned rows unused for
`UNUSED_DAYS` are dropped by a daily job.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TtsAudio
from app.providers.config import ResolvedModel, TenantProviderContext
from app.providers.tts import Language, TextToSpeech, get_tts

# Per tenant, unpinned rows only. A sentence of mp3 is tens of KB, so this keeps
# thousands of sentences without growing the database much.
CACHE_MAX_BYTES = 200 * 1024 * 1024
UNUSED_DAYS = 30


@dataclass(frozen=True)
class Audio:
    audio: bytes
    mime_type: str
    cached: bool


def cache_key(text: str, language: str, voice: str, speed: float, model: ResolvedModel) -> str:
    material = [text, language, voice, round(speed, 2), model.connection, model.model]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False).encode()).hexdigest()


async def read_aloud(
    session: AsyncSession,
    ctx: TenantProviderContext,
    text: str,
    *,
    language: Language,
    speed: float,
    user_id: uuid.UUID | None,
    tts: TextToSpeech | None = None,
) -> Audio:
    """Raises NoModelConfiguredError when the tenant has no read-aloud route, and
    SpeechSynthesisError when no model in it could read the text."""
    tts = tts or get_tts(ctx)
    # Audio from any model in the route will do, the earliest one first: a fallback's
    # recording beats paying the primary for the same sentence again.
    keys = [
        cache_key(text, language, voice, speed, model) for model, voice in tts.candidates(language)
    ]
    if keys:
        rows = {
            row.key: row
            for row in await session.scalars(
                select(TtsAudio).where(TtsAudio.tenant_id == ctx.tenant_id, TtsAudio.key.in_(keys))
            )
        }
        hit = next((rows[k] for k in keys if k in rows), None)
        if hit is not None:
            await session.execute(
                update(TtsAudio).where(TtsAudio.id == hit.id).values(last_used_at=func.now())
            )
            audio = await session.scalar(select(TtsAudio.audio).where(TtsAudio.id == hit.id))
            await session.commit()
            if audio is not None:
                return Audio(audio, hit.mime_type, cached=True)

    speech = await tts.synthesize(text, language=language, speed=speed, user_id=user_id)
    served_by = next(
        m for m in tts.models if (m.connection, m.model) == (speech.connection, speech.model)
    )
    await session.execute(
        insert(TtsAudio)
        .values(
            tenant_id=ctx.tenant_id,
            user_id=user_id,
            key=cache_key(text, language, speech.voice, speed, served_by),
            language=language,
            connection_name=speech.connection,
            model=speech.model,
            voice=speech.voice,
            mime_type=speech.mime_type,
            audio=speech.audio,
            size=len(speech.audio),
        )
        # Two learners asking for the same sentence at once: keep the first.
        .on_conflict_do_nothing(index_elements=["tenant_id", "key"])
    )
    await evict(session, ctx.tenant_id)
    await session.commit()
    return Audio(speech.audio, speech.mime_type, cached=False)


async def evict(
    session: AsyncSession, tenant_id: uuid.UUID, max_bytes: int = CACHE_MAX_BYTES
) -> None:
    """Delete the tenant's least recently used unpinned audio beyond `max_bytes`."""
    newest_first = (
        select(
            TtsAudio.id,
            func.sum(TtsAudio.size)
            .over(order_by=(TtsAudio.last_used_at.desc(), TtsAudio.id.desc()))
            .label("running"),
        )
        .where(TtsAudio.tenant_id == tenant_id, TtsAudio.pinned.is_(False))
        .subquery()
    )
    await session.execute(
        delete(TtsAudio).where(
            TtsAudio.id.in_(select(newest_first.c.id).where(newest_first.c.running > max_bytes))
        )
    )


async def clear_user_audio(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Delete the unpinned audio `user_id` first asked for; returns how many rows."""
    statement = delete(TtsAudio).where(TtsAudio.user_id == user_id, TtsAudio.pinned.is_(False))
    result: CursorResult[Any] = await session.execute(statement)  # type: ignore[assignment]
    await session.commit()
    return result.rowcount


async def drop_unused(session: AsyncSession, now: datetime, days: int = UNUSED_DAYS) -> int:
    """Delete unpinned audio no one has played for `days` days, in every tenant."""
    statement = delete(TtsAudio).where(
        TtsAudio.pinned.is_(False), TtsAudio.last_used_at < now - timedelta(days=days)
    )
    result: CursorResult[Any] = await session.execute(statement)  # type: ignore[assignment]
    await session.commit()
    return result.rowcount
