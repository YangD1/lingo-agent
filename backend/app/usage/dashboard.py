"""The usage dashboard (ADR 0034 §2): totals, a daily series and three groupings over
`llm_usage`, with an estimated cost where the tenant entered prices (§3).

Same scope as `summarize_usage`: the tenant's own calls and its members' calls on its
connections (ADR 0031 §8). Days are UTC.
"""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Date, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage, User


@dataclass(frozen=True)
class Price:
    """What one `connection:model` costs, in the tenant's currency; None: not entered."""

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    per_kchar: float | None = None
    per_minute: float | None = None


@dataclass(frozen=True)
class Cost:
    amount: float
    # Some usage had no price entered, so `amount` leaves it out.
    partial: bool


def cost_of(
    price: Price | None,
    *,
    input_tokens: int,
    output_tokens: int,
    characters: int,
    audio_minutes: float,
) -> Cost | None:
    """None: nothing priced for this model. Each part counts only with its price."""
    if price is None:
        return None
    parts = (
        (input_tokens, price.input_per_mtok, 1_000_000),
        (output_tokens, price.output_per_mtok, 1_000_000),
        (characters, price.per_kchar, 1_000),
        (audio_minutes, price.per_minute, 1),
    )
    if all(unit_price is None for _, unit_price, _ in parts):
        return None
    amount = sum(used * unit_price / per for used, unit_price, per in parts if unit_price)
    partial = any(used > 0 and unit_price is None for used, unit_price, _ in parts)
    return Cost(amount=amount, partial=partial)


@dataclass
class Tally:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    audio_minutes: float = 0.0
    errors: int = 0
    fallbacks: int = 0
    # None until some call in it was priced.
    cost: float | None = None
    # Some calls in it had usage without a price.
    cost_partial: bool = False

    def add(self, row: "UsageRow", cost: Cost | None) -> None:
        self.calls += row.calls
        self.input_tokens += row.input_tokens
        self.output_tokens += row.output_tokens
        self.characters += row.characters
        self.audio_minutes += row.audio_minutes
        self.errors += row.errors
        self.fallbacks += row.fallbacks
        if cost is None:
            self.cost_partial = self.cost_partial or row.has_usage
        else:
            self.cost = (self.cost or 0.0) + cost.amount
            self.cost_partial = self.cost_partial or cost.partial


@dataclass(frozen=True)
class DayTally:
    day: date
    tally: Tally


@dataclass(frozen=True)
class TaskTally:
    task: str
    background: bool
    tally: Tally


@dataclass(frozen=True)
class ModelTally:
    connection: str
    model: str
    tally: Tally


@dataclass(frozen=True)
class MemberTally:
    # None: the tenant's own calls; else the member's display name or email.
    member: str | None
    tally: Tally


@dataclass
class Dashboard:
    total: Tally = field(default_factory=Tally)
    days: list[DayTally] = field(default_factory=list)
    tasks: list[TaskTally] = field(default_factory=list)
    models: list[ModelTally] = field(default_factory=list)
    members: list[MemberTally] = field(default_factory=list)
    # Some call was priced: show costs at all.
    priced: bool = False


@dataclass(frozen=True)
class UsageRow:
    day: date
    member: str | None
    connection: str
    model: str
    task: str
    background: bool
    calls: int
    input_tokens: int
    output_tokens: int
    characters: int
    audio_minutes: float
    errors: int
    fallbacks: int

    @property
    def has_usage(self) -> bool:
        return (
            self.input_tokens + self.output_tokens + self.characters > 0 or self.audio_minutes > 0
        )


async def _rows(session: AsyncSession, tenant_id: uuid.UUID, since: datetime) -> list[UsageRow]:
    day = cast(func.timezone("UTC", LLMUsage.created_at), Date).label("day")
    own = LLMUsage.tenant_id == tenant_id
    member = case(
        (own, literal(None)), else_=func.coalesce(User.display_name, User.email, "?")
    ).label("member")
    keys = (day, member, LLMUsage.connection_name, LLMUsage.model, LLMUsage.task)
    stmt = (
        select(
            *keys,
            LLMUsage.background,
            func.count(),
            func.coalesce(func.sum(LLMUsage.input_tokens), 0),
            func.coalesce(func.sum(LLMUsage.output_tokens), 0),
            func.coalesce(func.sum(LLMUsage.characters), 0),
            func.coalesce(func.sum(LLMUsage.audio_seconds), 0.0),
            func.count(case((LLMUsage.status != "ok", 1))),
            func.count(case((LLMUsage.is_fallback, 1))),
        )
        .outerjoin(User, User.id == LLMUsage.user_id)
        .where(or_(own, LLMUsage.billed_tenant_id == tenant_id), LLMUsage.created_at >= since)
        .group_by(*keys, LLMUsage.background)
    )
    return [
        UsageRow(
            day=r[0],
            member=r[1],
            connection=r[2],
            model=r[3],
            task=r[4],
            background=r[5],
            calls=r[6],
            input_tokens=int(r[7]),
            output_tokens=int(r[8]),
            characters=int(r[9]),
            audio_minutes=float(r[10]) / 60,
            errors=r[11],
            fallbacks=r[12],
        )
        for r in await session.execute(stmt)
    ]


def build_dashboard(
    rows: Iterable[UsageRow],
    prices: Mapping[tuple[str, str], Price],
    first_day: date,
    last_day: date,
) -> Dashboard:
    """Every day from `first_day` to `last_day` gets an entry, zero when idle. Groups are
    sorted by calls, most first; the tenant's own calls lead the members."""
    out = Dashboard()
    days = {first_day + timedelta(days=i): Tally() for i in range((last_day - first_day).days + 1)}
    tasks: dict[tuple[str, bool], Tally] = {}
    models: dict[tuple[str, str], Tally] = {}
    members: dict[str | None, Tally] = {}
    for row in rows:
        cost = cost_of(
            prices.get((row.connection, row.model)),
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            characters=row.characters,
            audio_minutes=row.audio_minutes,
        )
        out.priced = out.priced or cost is not None
        for tally in (
            out.total,
            days.setdefault(row.day, Tally()),
            tasks.setdefault((row.task, row.background), Tally()),
            models.setdefault((row.connection, row.model), Tally()),
            members.setdefault(row.member, Tally()),
        ):
            tally.add(row, cost)
    out.days = [DayTally(day, tally) for day, tally in sorted(days.items())]
    out.tasks = [
        TaskTally(task, background, tally)
        for (task, background), tally in sorted(tasks.items(), key=lambda i: (-i[1].calls, i[0]))
    ]
    out.models = [
        ModelTally(connection, model, tally)
        for (connection, model), tally in sorted(models.items(), key=lambda i: (-i[1].calls, i[0]))
    ]
    out.members = [
        MemberTally(member, tally)
        for member, tally in sorted(
            members.items(), key=lambda i: (i[0] is not None, -i[1].calls, i[0] or "")
        )
    ]
    return out


async def usage_dashboard(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    first_day: date,
    last_day: date,
    prices: Mapping[tuple[str, str], Price],
) -> Dashboard:
    rows = await _rows(session, tenant_id, datetime.combine(first_day, time.min, UTC))
    return build_dashboard(rows, prices, first_day, last_day)
