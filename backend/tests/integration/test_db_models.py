import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    LLMUsage,
    ProviderConnection,
    Tenant,
    TenantMember,
    User,
)

URL = "https://api.example.com/v1"


async def _user_with_tenant(session: AsyncSession, email: str = "a@example.com") -> User:
    tenant = Tenant(name="personal", kind="personal")
    user = User(email=email, password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
    await session.flush()
    return user


async def _tenant_of(session: AsyncSession, user: User) -> Tenant:
    member = await session.scalar(select(TenantMember).where(TenantMember.user_id == user.id))
    assert member is not None
    tenant = await session.get(Tenant, member.tenant_id)
    assert tenant is not None
    return tenant


async def test_email_is_unique(db_session: AsyncSession) -> None:
    await _user_with_tenant(db_session, "dup@example.com")
    db_session.add(User(email="dup@example.com", password_hash="y"))
    with pytest.raises(IntegrityError, match="uq_users_email"):
        await db_session.flush()


async def test_provider_kind_is_checked(db_session: AsyncSession) -> None:
    user = await _user_with_tenant(db_session)
    tenant = await _tenant_of(db_session, user)
    db_session.add(
        ProviderConnection(tenant_id=tenant.id, name="x", kind="not-a-kind", base_url=URL)
    )
    with pytest.raises(IntegrityError, match="ck_provider_connections_kind"):
        await db_session.flush()


async def test_connection_name_unique_per_tenant(db_session: AsyncSession) -> None:
    user = await _user_with_tenant(db_session)
    tenant = await _tenant_of(db_session, user)
    db_session.add(
        ProviderConnection(tenant_id=tenant.id, name="deepseek", kind="deepseek", base_url=URL)
    )
    await db_session.flush()
    db_session.add(
        ProviderConnection(tenant_id=tenant.id, name="deepseek", kind="deepseek", base_url=URL)
    )
    with pytest.raises(IntegrityError, match="uq_provider_connections_tenant_id_name"):
        await db_session.flush()


async def test_deleting_tenant_cascades(db_session: AsyncSession) -> None:
    user = await _user_with_tenant(db_session)
    tenant = await _tenant_of(db_session, user)
    db_session.add_all(
        [
            ProviderConnection(tenant_id=tenant.id, name="deepseek", kind="deepseek", base_url=URL),
            Conversation(tenant_id=tenant.id, user_id=user.id),
        ]
    )
    await db_session.commit()

    await db_session.delete(tenant)
    await db_session.commit()
    db_session.expunge_all()

    assert await db_session.scalar(select(ProviderConnection)) is None
    assert await db_session.scalar(select(Conversation)) is None
    assert await db_session.scalar(select(TenantMember)) is None
    assert await db_session.get(User, user.id) is not None  # users outlive tenants


async def test_usage_survives_user_deletion(db_session: AsyncSession) -> None:
    user = await _user_with_tenant(db_session)
    tenant = await _tenant_of(db_session, user)
    db_session.add(
        LLMUsage(
            tenant_id=tenant.id,
            user_id=user.id,
            task="chat",
            connection_name="deepseek",
            model="deepseek-chat",
            input_tokens=10,
            output_tokens=5,
            latency_ms=120,
            status="ok",
        )
    )
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()
    db_session.expunge_all()

    usage = await db_session.scalar(select(LLMUsage))
    assert usage is not None
    assert usage.user_id is None
