"""Rewriting new articles ahead of time, so they open without a wait (Q42g, ADR 0025).

For each tenant, the levels its learners read at (those who left the switch on) and
the feeds they follow give (feed, level) pairs; for each pair, the newest
`reading.prerewrite_per_feed` rewritable articles of the last `reading.prerewrite_days`
days that have no version at that level yet are rewritten, one at a time. The tenant's
daily background budget is checked before each one (it may end a little past it,
Q40b). A version that failed is left for a learner to retry by opening it.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import Rules
from app.db.models import REWRITABLE_LICENSES, Article, ArticleVersion, TenantMember
from app.scheduler import budget, prefs
from app.services.news import feeds
from app.services.reading import versions
from app.services.reading.worker import ReadingWorker

logger = logging.getLogger(__name__)

type Pairs = dict[uuid.UUID, set[tuple[uuid.UUID, CefrLevel]]]


async def wanted_pairs(session: AsyncSession, rules: Rules) -> Pairs:
    """Per tenant, the (feed, level) pairs some learner with the switch on reads."""
    pairs: Pairs = defaultdict(set)
    members = await session.execute(select(TenantMember.tenant_id, TenantMember.user_id))
    for tenant_id, user_id in members.all():
        if not await prefs.is_enabled(session, user_id, prefs.ARTICLE_PREREWRITE):
            continue
        level = await versions.reading_level(session, user_id, rules)
        if level not in rules.reading.levels:
            continue
        for feed_id in await feeds.followed_feed_ids(session, user_id, tenant_id):
            pairs[tenant_id].add((feed_id, level))
    return pairs


async def due_articles(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    feed_id: uuid.UUID,
    level: CefrLevel,
    *,
    since: datetime,
    limit: int,
) -> list[int]:
    """The newest rewritable articles of the feed since `since` with no version at this
    level in this tenant (whatever its status)."""
    versioned = exists().where(
        ArticleVersion.article_id == Article.id,
        ArticleVersion.tenant_id == tenant_id,
        ArticleVersion.level == level,
    )
    newest = (
        select(Article.id)
        .where(
            Article.feed_id == feed_id,
            Article.published_at >= since,
            Article.summary_only.is_(False),
            Article.license.in_(REWRITABLE_LICENSES),
        )
        .order_by(Article.published_at.desc(), Article.id.desc())
        .limit(limit)
        .subquery()
    )
    # Only among the newest `limit`: an older article stays unwritten until opened.
    return list(
        await session.scalars(
            select(Article.id).where(Article.id.in_(select(newest.c.id)), ~versioned)
        )
    )


async def prerewrite(
    sessionmaker: async_sessionmaker[AsyncSession],
    worker: ReadingWorker,
    *,
    rules: Rules,
    now: datetime,
) -> str | None:
    """One `article_prerewrite` run; returns `budget.EXHAUSTED` when every tenant with
    work was out of budget before writing anything, else None."""
    since = now - timedelta(days=rules.reading.prerewrite_days)
    async with sessionmaker() as session:
        pairs = await wanted_pairs(session, rules)
    written = 0
    stopped: set[uuid.UUID] = set()
    for tenant_id, tenant_pairs in pairs.items():
        for feed_id, level in sorted(tenant_pairs, key=lambda p: (str(p[0]), p[1])):
            async with sessionmaker() as session:
                articles = await due_articles(
                    session,
                    tenant_id,
                    feed_id,
                    level,
                    since=since,
                    limit=rules.reading.prerewrite_per_feed,
                )
            for article_id in articles:
                async with sessionmaker() as session:
                    if (await budget.load(session, tenant_id, now)).exhausted:
                        stopped.add(tenant_id)
                        break
                if await worker.generate(tenant_id, article_id, level) is not None:
                    written += 1
            if tenant_id in stopped:
                logger.info("background budget used up; rewriting stopped for %s", tenant_id)
                break
    logger.info("article_prerewrite: %d written, %d tenants out of budget", written, len(stopped))
    return budget.EXHAUSTED if stopped and written == 0 else None
