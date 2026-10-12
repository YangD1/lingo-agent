"""Org invites and memberships (ADR 0031 §1-2)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage, OrgInvite, OrgMembership, Tenant, TenantMember, User
from app.org.quotas import DEFAULT_QUOTAS


async def _account(session: AsyncSession, email: str) -> tuple[User, Tenant]:
    tenant = Tenant(name=email, kind="personal")
    user = User(email=email, password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
    await session.flush()
    return user, tenant


def _membership(sponsor: Tenant, user: User, tenant: Tenant, **kw: object) -> OrgMembership:
    return OrgMembership(
        sponsor_tenant_id=sponsor.id,
        member_user_id=user.id,
        member_tenant_id=tenant.id,
        quotas=DEFAULT_QUOTAS.model_dump(),
        **kw,
    )


async def test_new_tenant_gets_default_member_quotas(db_session: AsyncSession) -> None:
    _, tenant = await _account(db_session, "owner@example.com")
    await db_session.refresh(tenant)
    assert tenant.member_default_quotas == DEFAULT_QUOTAS.model_dump()


async def test_one_active_membership_per_member(db_session: AsyncSession) -> None:
    _, a = await _account(db_session, "a@example.com")
    _, b = await _account(db_session, "b@example.com")
    member, own = await _account(db_session, "m@example.com")
    db_session.add(_membership(a, member, own, status="left"))
    db_session.add(_membership(a, member, own))
    await db_session.flush()
    db_session.add(_membership(b, member, own))
    with pytest.raises(IntegrityError, match="uq_org_memberships_active_member"):
        await db_session.flush()


async def test_cannot_sponsor_self(db_session: AsyncSession) -> None:
    user, tenant = await _account(db_session, "a@example.com")
    db_session.add(_membership(tenant, user, tenant))
    with pytest.raises(IntegrityError, match="ck_org_memberships_not_self"):
        await db_session.flush()


async def test_deleting_main_account_ends_memberships_and_invites(
    db_session: AsyncSession,
) -> None:
    owner, sponsor = await _account(db_session, "a@example.com")
    member, own = await _account(db_session, "m@example.com")
    invite = OrgInvite(
        tenant_id=sponsor.id,
        code_hash="0" * 64,
        created_by=owner.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(invite)
    await db_session.flush()
    membership = _membership(sponsor, member, own, invite_id=invite.id)
    db_session.add(membership)
    await db_session.flush()
    await db_session.delete(sponsor)
    await db_session.flush()
    db_session.expunge_all()
    assert await db_session.get(OrgMembership, membership.id) is None
    assert await db_session.get(OrgInvite, invite.id) is None


async def test_invite_max_uses_is_checked(db_session: AsyncSession) -> None:
    _, sponsor = await _account(db_session, "a@example.com")
    db_session.add(
        OrgInvite(
            tenant_id=sponsor.id,
            code_hash="1" * 64,
            expires_at=datetime.now(UTC),
            max_uses=0,
        )
    )
    with pytest.raises(IntegrityError, match="ck_org_invites_max_uses"):
        await db_session.flush()


async def test_usage_section_is_checked(db_session: AsyncSession) -> None:
    _, tenant = await _account(db_session, "a@example.com")
    db_session.add(
        LLMUsage(
            tenant_id=tenant.id,
            task="chat",
            connection_name="x",
            model="m",
            latency_ms=1,
            status="ok",
            section="video",
            billed_tenant_id=uuid.uuid4(),
        )
    )
    with pytest.raises(IntegrityError, match="ck_llm_usage_section"):
        await db_session.flush()
