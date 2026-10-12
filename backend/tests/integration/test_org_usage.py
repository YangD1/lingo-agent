"""A member's quota use on the main account (ADR 0031 §4, §6)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    LLMUsage,
    OrgMembership,
    SpeakingSession,
    Tenant,
    TenantMember,
    User,
)
from app.org.quotas import Limit, Quotas
from app.org.usage import Used, exhausted_sections, left, membership_use, realtime_seconds_left

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


async def _account(session: AsyncSession, email: str) -> tuple[User, Tenant]:
    tenant = Tenant(name=email, kind="personal")
    user = User(email=email, password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
    await session.flush()
    return user, tenant


async def _membership(session: AsyncSession, quotas: Quotas) -> OrgMembership:
    _, sponsor = await _account(session, "main@example.com")
    user, own = await _account(session, "member@example.com")
    membership = OrgMembership(
        sponsor_tenant_id=sponsor.id,
        member_user_id=user.id,
        member_tenant_id=own.id,
        quotas=quotas.model_dump(),
    )
    session.add(membership)
    await session.flush()
    return membership


def _usage(
    m: OrgMembership,
    section: str,
    at: datetime,
    *,
    billed: bool = True,
    tokens: int = 0,
    characters: int | None = None,
    seconds: float | None = None,
) -> LLMUsage:
    return LLMUsage(
        tenant_id=m.member_tenant_id,
        user_id=m.member_user_id,
        task="t",
        connection_name="c",
        model="m",
        input_tokens=tokens,
        output_tokens=tokens,
        latency_ms=1,
        status="ok",
        section=section,
        billed_tenant_id=m.sponsor_tenant_id if billed else None,
        characters=characters,
        audio_seconds=seconds,
        created_at=at,
    )


def test_left_takes_the_tighter_cap() -> None:
    assert left(Limit(), Used(day=5, month=50)) is None
    assert left(Limit(daily=10), Used(day=4, month=50)) == 6
    assert left(Limit(daily=10, monthly=52), Used(day=4, month=50)) == 2
    assert left(Limit(daily=10), Used(day=12, month=12)) == 0


async def test_counts_only_this_members_calls_on_the_main_account(
    db_session: AsyncSession,
) -> None:
    m = await _membership(db_session, Quotas())
    yesterday, last_month = NOW - timedelta(days=1), NOW - timedelta(days=13)
    db_session.add_all(
        [
            _usage(m, "llm", NOW, tokens=100),  # 200 tokens today
            _usage(m, "embedding", NOW, tokens=5),
            _usage(m, "llm", yesterday, tokens=1000),
            _usage(m, "llm", last_month, tokens=99_999),  # September
            _usage(m, "llm", NOW, billed=False, tokens=50_000),  # their own connection
            _usage(m, "tts", NOW, characters=300),
            _usage(m, "asr", NOW, seconds=90),
            _usage(m, "pronunciation", yesterday, seconds=30),
        ]
    )
    conversation = Conversation(tenant_id=m.member_tenant_id, user_id=m.member_user_id)
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        SpeakingSession(
            user_id=m.member_user_id,
            conversation_id=conversation.id,
            mode="realtime",
            level="B1",
            call_seconds=600,
            billed_tenant_id=m.sponsor_tenant_id,
            started_at=NOW,
        )
    )
    await db_session.flush()

    use = await membership_use(db_session, m, NOW)
    assert use["text"] == Used(day=210, month=2210)
    assert use["tts"] == Used(day=300, month=300)
    assert use["asr"] == Used(day=1.5, month=1.5)
    assert use["pronunciation"] == Used(day=0, month=0.5)
    assert use["realtime"] == Used(day=10, month=10)


async def test_used_up_or_zero_caps_exhaust_their_sections(db_session: AsyncSession) -> None:
    quotas = Quotas(text=Limit(daily=200), tts=Limit(daily=0), asr=Limit(monthly=10))
    m = await _membership(db_session, quotas)
    assert await exhausted_sections(db_session, m, NOW) == {"tts"}
    db_session.add(_usage(m, "llm", NOW, tokens=100))
    await db_session.flush()
    assert await exhausted_sections(db_session, m, NOW) == {"tts", "llm", "embedding"}
    # A new day starts the daily cap again.
    assert await exhausted_sections(db_session, m, NOW + timedelta(days=1)) == {"tts"}


async def test_realtime_seconds_left(db_session: AsyncSession) -> None:
    m = await _membership(db_session, Quotas(realtime=Limit(daily=30, monthly=100)))
    assert await realtime_seconds_left(db_session, m, NOW) == 30 * 60
    m.quotas = Quotas().model_dump()
    assert await realtime_seconds_left(db_session, m, NOW) is None
