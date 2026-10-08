"""Background features a learner can switch off (ADR 0025 §6).

Each entry is one kind of background work done for a learner, with its default and the
`features.yaml` feature whose estimates the settings page shows next to its switch.
Tasks that add background work add an entry here: article rewriting (42), AI example
sentences (44, off by default), the weekly diagnosis (46).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserBackgroundPref


@dataclass(frozen=True)
class BackgroundFeature:
    key: str
    default: bool
    # The `app/usage/features.yaml` feature it runs under (for its AI badge).
    usage_feature: str


PRACTICE_PREFETCH = "practice_prefetch"
ARTICLE_PREREWRITE = "article_prerewrite"

FEATURES: tuple[BackgroundFeature, ...] = (
    # After a set is done, the next one is generated so it starts without a wait.
    BackgroundFeature(PRACTICE_PREFETCH, default=True, usage_feature="practice_set"),
    # New articles of the feeds the learner follows are rewritten for their level, so
    # they open without a wait (Q42g).
    BackgroundFeature(ARTICLE_PREREWRITE, default=True, usage_feature="reading_prerewrite"),
)
_BY_KEY = {feature.key: feature for feature in FEATURES}


class UnknownFeatureError(ValueError):
    pass


def get_feature(key: str) -> BackgroundFeature:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise UnknownFeatureError(key) from None


async def load(session: AsyncSession, user_id: uuid.UUID) -> dict[str, bool]:
    """Every feature's switch for this learner, defaults filled in."""
    saved = {
        row.feature: row.enabled
        for row in await session.scalars(
            select(UserBackgroundPref).where(UserBackgroundPref.user_id == user_id)
        )
    }
    return {feature.key: saved.get(feature.key, feature.default) for feature in FEATURES}


async def is_enabled(session: AsyncSession, user_id: uuid.UUID, key: str) -> bool:
    feature = get_feature(key)
    enabled = await session.scalar(
        select(UserBackgroundPref.enabled).where(
            UserBackgroundPref.user_id == user_id, UserBackgroundPref.feature == key
        )
    )
    return feature.default if enabled is None else enabled


async def set_enabled(session: AsyncSession, user_id: uuid.UUID, key: str, enabled: bool) -> None:
    get_feature(key)
    statement = insert(UserBackgroundPref).values(user_id=user_id, feature=key, enabled=enabled)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[UserBackgroundPref.user_id, UserBackgroundPref.feature],
            set_={"enabled": enabled, "updated_at": func.now()},
        )
    )
