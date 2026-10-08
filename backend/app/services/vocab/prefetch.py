"""AI example sentences written ahead of time, so the card shows them when turned over
(task 44, Q44a-e).

For each learner who left the switch on: the cards due within
`vocab.examples_prefetch.ahead_hours` and the next day's new words (queue order), those
with no Tatoeba sentence and no cached AI sentences at the learner's level, at most
`per_learner` of them. The level is the one the "AI examples" button uses
(`examples.level_for`), so the cache serves both. The tenant's daily background
budget is checked before each word (it may end a little past it, Q40b); a provider
error stops that tenant for this run.
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from langchain_core.runnables import RunnableConfig
from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.rules import Rules
from app.db.models import TenantMember, UserCard, UserWordBook, Word, WordExample, WordSentence
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context
from app.scheduler import budget, prefs
from app.services.vocab import examples
from app.services.vocab.queue import daily_limit, next_new

logger = logging.getLogger(__name__)


def _uncovered(tenant_id: uuid.UUID, level: str) -> tuple[ColumnElement[bool], ...]:
    """Words with neither a real sentence nor cached AI ones at this level."""
    return (
        ~exists().where(WordSentence.word_id == Word.id),
        ~exists().where(
            WordExample.tenant_id == tenant_id,
            WordExample.word_id == Word.id,
            WordExample.cefr == level,
        ),
    )


async def words_for(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    level: str,
    *,
    rules: Rules,
    now: datetime,
) -> list[Word]:
    """The learner's coming words that need AI sentences: due reviews first (soonest
    first), then new words; at most `per_learner`."""
    config = rules.vocab.examples_prefetch
    uncovered = _uncovered(tenant_id, level)
    due = list(
        await session.scalars(
            select(Word)
            .join(UserCard, UserCard.word_id == Word.id)
            .where(
                UserCard.user_id == user_id,
                UserCard.status == "learning",
                UserCard.due <= now + timedelta(hours=config.ahead_hours),
                *uncovered,
            )
            .order_by(UserCard.due, UserCard.id)
            .limit(config.per_learner)
        )
    )
    plan = await session.get(UserWordBook, user_id)
    coming = [
        item.word for item in await next_new(session, user_id, plan, daily_limit(plan, rules))
    ]
    needed = set(
        await session.scalars(
            select(Word.id).where(Word.id.in_([w.id for w in coming]), *uncovered)
        )
    )
    seen = {w.id for w in due}
    new = [w for w in coming if w.id in needed and w.id not in seen]
    return (due + new)[: config.per_learner]


async def _learners(session: AsyncSession) -> dict[uuid.UUID, list[uuid.UUID]]:
    by_tenant: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    members = await session.execute(
        select(TenantMember.tenant_id, TenantMember.user_id).order_by(
            TenantMember.tenant_id, TenantMember.user_id
        )
    )
    for tenant_id, user_id in members.all():
        if await prefs.is_enabled(session, user_id, prefs.WORD_EXAMPLES_PREFETCH):
            by_tenant[tenant_id].append(user_id)
    return by_tenant


class _TenantStopped(Exception):
    """No more calls for this tenant in this run (budget, no model, provider error)."""

    def __init__(self, reason: str, written: int) -> None:
        self.reason = reason
        # Words written for the tenant before it stopped.
        self.written = written


async def _tenant(
    sessionmaker: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    learners: Sequence[uuid.UUID],
    *,
    rules: Rules,
    now: datetime,
) -> int:
    """Writes the tenant's learners' sentences; returns how many words got them."""
    async with sessionmaker() as session:
        ctx = await load_provider_context(session, tenant_id)
    written = 0
    for user_id in learners:
        async with sessionmaker() as session:
            level = await examples.level_for(session, user_id)
            words = await words_for(session, user_id, tenant_id, level, rules=rules, now=now)
        for word in words:
            async with sessionmaker() as session:
                if (await budget.load(session, tenant_id, now)).exhausted:
                    raise _TenantStopped(budget.EXHAUSTED, written)
                config: RunnableConfig = {"metadata": {"user_id": str(user_id), "background": True}}
                try:
                    await examples.examples(session, ctx, word, level, config)
                except examples.ExamplesInvalidError:
                    # Left for the button; the next run tries it again.
                    logger.info("no valid example sentences for word %s", word.id)
                    continue
                except NoModelConfiguredError:
                    raise _TenantStopped("no_model", written) from None
                except Exception:
                    # Details stay in the server log; vendor errors can echo input.
                    logger.exception("writing examples for word %s failed", word.id)
                    raise _TenantStopped("provider_error", written) from None
            written += 1
    return written


async def prefetch(
    sessionmaker: async_sessionmaker[AsyncSession], *, rules: Rules, now: datetime
) -> str | None:
    """One `word_examples_prefetch` run; returns `budget.EXHAUSTED` when every tenant
    with work was out of budget before writing anything, else None."""
    async with sessionmaker() as session:
        by_tenant = await _learners(session)
    written = 0
    out_of_budget = 0
    for tenant_id, learners in by_tenant.items():
        try:
            written += await _tenant(sessionmaker, tenant_id, learners, rules=rules, now=now)
        except _TenantStopped as stop:
            logger.info("word_examples_prefetch stopped for %s: %s", tenant_id, stop.reason)
            written += stop.written
            out_of_budget += stop.reason == budget.EXHAUSTED
    logger.info(
        "word_examples_prefetch: %d words written, %d tenants out of budget",
        written,
        out_of_budget,
    )
    return budget.EXHAUSTED if out_of_budget and written == 0 else None
