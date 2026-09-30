"""The dashboard's study advice: cached per learner, refreshed in the background.

Opening the dashboard reads the cache and never waits for a model (P1 plan §7.5.2).
The advice is regenerated when it is older than `STALE_AFTER`, when today's candidate
actions are not the ones it was written for, or when it was written in another UI
language (Q18b), or at once after a placement test (task 21.3: its result page shows
the advice, which should reflect the new result). Items whose candidate is gone are
hidden at once and templates fill in (Q18d), so the page never points at work already
done.

Generation runs in-process, one task per learner at a time, like reflection: no task
queue, the backend is a single worker process. A missing model or a failed call is
stored as such and shows template advice until the next refresh.
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import GrammarCatalog, get_grammar_catalog
from app.adaptive.rules import Rules, get_rules
from app.advice import writer
from app.advice.candidates import Candidate, candidates
from app.advice.writer import Item, fill
from app.db.models import LearningAdvice, PlacementSession, UserProfile
from app.memory.reflection import memory_language
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context

logger = logging.getLogger(__name__)

Locale = Literal["en", "zh-CN"]
Status = Literal["ai", "no_model", "failed", "empty"]
STALE_AFTER = timedelta(hours=12)
# Automatic regeneration at most this often: candidates can flip back and forth (a
# word falling due during a review session) and each change would cost a call.
MIN_INTERVAL = timedelta(minutes=10)
BY_HAND_EVERY = timedelta(hours=1)


def advice_locale(raw: str | None) -> Locale:
    return "zh-CN" if raw and raw.lower().startswith("zh") else "en"


@dataclass(frozen=True, slots=True)
class Advice:
    # Best first, each with its live candidate (current numbers for the page).
    items: list[tuple[Item, Candidate]]
    status: Status | None
    generated_at: datetime | None
    # Due for regeneration; the caller schedules it.
    stale: bool
    # When the learner may press "refresh" again; None = now.
    by_hand_after: datetime | None


def needs_refresh(
    row: LearningAdvice | None,
    found: Sequence[Candidate],
    locale: Locale,
    now: datetime,
    placed_at: datetime | None = None,
) -> bool:
    """`placed_at`: when the latest placement test was finished."""
    if row is None:
        return True
    if placed_at is not None and placed_at > row.generated_at:
        return True
    age = now - row.generated_at
    changed = row.locale != locale or set(row.candidate_ids) != {c.id for c in found}
    return age >= STALE_AFTER or (changed and age >= MIN_INTERVAL)


def stored_items(row: LearningAdvice | None, locale: Locale) -> list[Item]:
    """The model's items, if written in this language; others count as templates."""
    if row is None or row.locale != locale:
        return []
    return [Item(i["candidate_id"], i["title"], i["reason"]) for i in row.items]


def by_hand_after(row: LearningAdvice | None, now: datetime) -> datetime | None:
    if row is None or row.refreshed_by_hand_at is None:
        return None
    after = row.refreshed_by_hand_at + BY_HAND_EVERY
    return after if after > now else None


async def read(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    tz: ZoneInfo,
    locale: Locale,
    now: datetime | None = None,
) -> Advice:
    """May rebuild stale mastery rows first; the caller commits."""
    now = now or datetime.now(UTC)
    found = await candidates(session, user_id, rules=rules, catalog=catalog, tz=tz, now=now)
    row = await session.get(LearningAdvice, user_id)
    placed_at = await session.scalar(
        select(func.max(PlacementSession.finished_at)).where(
            PlacementSession.user_id == user_id, PlacementSession.status == "done"
        )
    )
    by_id = {c.id: c for c in found}
    return Advice(
        items=[(item, by_id[item.candidate_id]) for item in fill(stored_items(row, locale), found)],
        status=row.status if row else None,  # type: ignore[arg-type]  # CHECK constraint
        generated_at=row.generated_at if row else None,
        stale=needs_refresh(row, found, locale, now, placed_at),
        by_hand_after=by_hand_after(row, now),
    )


async def _save(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    items: Sequence[Item],
    found: Sequence[Candidate],
    locale: Locale,
    status: Status,
    now: datetime,
    by_hand: bool,
) -> None:
    values = {
        "items": [
            {"candidate_id": i.candidate_id, "title": i.title, "reason": i.reason} for i in items
        ],
        "candidate_ids": [c.id for c in found],
        "locale": locale,
        "status": status,
        "generated_at": now,
    }
    if by_hand:
        values["refreshed_by_hand_at"] = now
    await session.execute(
        insert(LearningAdvice)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=["user_id"], set_=values)
    )


class AdviceRefresher:
    """Regenerates learners' advice off the request path, one task per learner."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        enabled: bool = True,
        concurrency: int = 2,
    ) -> None:
        self._sessionmaker = sessionmaker
        self.enabled = enabled
        self._slots = asyncio.Semaphore(concurrency)
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def schedule(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        tz: ZoneInfo,
        locale: Locale,
        by_hand: bool = False,
    ) -> None:
        """Regenerate soon, unless already under way (which reads fresh data anyway)."""
        if not self.enabled or user_id in self._tasks:
            return
        self._tasks[user_id] = asyncio.create_task(
            self._guarded(user_id, tenant_id, tz, locale, by_hand), name=f"advice-{user_id}"
        )

    def is_busy(self, user_id: uuid.UUID) -> bool:
        return user_id in self._tasks

    async def wait_idle(self) -> None:
        """Wait for all scheduled work (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()

    async def _guarded(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, tz: ZoneInfo, locale: Locale, by_hand: bool
    ) -> None:
        try:
            async with self._slots:
                await self.generate(user_id, tenant_id, tz=tz, locale=locale, by_hand=by_hand)
        except Exception:
            logger.exception("advice generation failed for user %s", user_id)
        finally:
            self._tasks.pop(user_id, None)

    async def generate(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        tz: ZoneInfo,
        locale: Locale,
        by_hand: bool = False,
        now: datetime | None = None,
    ) -> Status:
        now = now or datetime.now(UTC)
        rules, catalog = get_rules(), get_grammar_catalog()
        # No connection is held during the model call.
        async with self._sessionmaker() as session:
            found = await candidates(session, user_id, rules=rules, catalog=catalog, tz=tz, now=now)
            profile = await session.get(UserProfile, user_id)
            ctx = await load_provider_context(session, tenant_id)
            await session.commit()  # stale mastery rows may have been rebuilt

        items: list[Item] = []
        status: Status = "empty"
        if found:
            config: RunnableConfig = {
                # llm_usage attributes the call to this learner.
                "metadata": {"user_id": str(user_id)},
                "tags": ["advice"],
            }
            try:
                items = await writer.write(
                    ctx, found, profile, language=memory_language(locale), config=config
                )
                status = "ai"
            except NoModelConfiguredError:
                status = "no_model"
            except Exception:
                logger.exception("advice model call failed for user %s", user_id)
                status = "failed"

        async with self._sessionmaker() as session:
            await _save(
                session,
                user_id,
                items=items,
                found=found,
                locale=locale,
                status=status,
                now=now,
                by_hand=by_hand,
            )
            await session.commit()
        return status
