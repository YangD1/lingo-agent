"""Invites and memberships: a main account lending its models to members (ADR 0031 §1-3).

Any personal tenant's owner may invite (Q65a). A member joins one main account at a
time (Q65b) and stays in their own personal tenant, so joining and leaving never move
learning data. Functions that change rows commit.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, case, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OrgInvite, OrgMembership, Tenant, TtsAudio, User
from app.org.quotas import Quotas

# Q65i: a week, one use, unless the main account picks otherwise.
DEFAULT_INVITE_DAYS = 7
MAX_INVITE_DAYS = 30


class InviteInvalidError(Exception):
    """Unknown, revoked, expired or used up: the joiner isn't told which."""


class OwnInviteError(Exception):
    pass


class AlreadyMemberError(Exception):
    pass


def new_code() -> str:
    return secrets.token_urlsafe(16)  # 128 bits


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def _open(now: datetime) -> ColumnElement[bool]:
    return and_(
        OrgInvite.revoked_at.is_(None),
        OrgInvite.expires_at > now,
        or_(OrgInvite.max_uses.is_(None), OrgInvite.used_count < OrgInvite.max_uses),
    )


async def create_invite(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    days: int,
    max_uses: int | None,
    now: datetime,
) -> tuple[OrgInvite, str]:
    """The new invite and its code: the code is only ever returned here."""
    code = new_code()
    invite = OrgInvite(
        tenant_id=tenant_id,
        code_hash=hash_code(code),
        created_by=user_id,
        expires_at=now + timedelta(days=days),
        max_uses=max_uses,
    )
    session.add(invite)
    await session.commit()
    return invite, code


async def open_invites(
    session: AsyncSession, tenant_id: uuid.UUID, now: datetime
) -> list[OrgInvite]:
    return list(
        (
            await session.scalars(
                select(OrgInvite)
                .where(OrgInvite.tenant_id == tenant_id, _open(now))
                .order_by(OrgInvite.created_at.desc())
            )
        ).all()
    )


async def revoke_invite(
    session: AsyncSession, tenant_id: uuid.UUID, invite_id: uuid.UUID, now: datetime
) -> bool:
    invite = await session.get(OrgInvite, invite_id)
    if invite is None or invite.tenant_id != tenant_id:
        return False
    if invite.revoked_at is None:
        invite.revoked_at = now
        await session.commit()
    return True


@dataclass(frozen=True)
class InvitePreview:
    sponsor: Tenant
    quotas: Quotas
    expires_at: datetime


async def preview_invite(session: AsyncSession, code: str, now: datetime) -> InvitePreview:
    """What joining with `code` would share, before the joiner agrees (Q65i)."""
    invite = await session.scalar(
        select(OrgInvite).where(OrgInvite.code_hash == hash_code(code), _open(now))
    )
    if invite is None:
        raise InviteInvalidError
    sponsor = await session.get(Tenant, invite.tenant_id)
    assert sponsor is not None  # FK, cascade
    return InvitePreview(
        sponsor=sponsor,
        quotas=Quotas.model_validate(sponsor.member_default_quotas),
        expires_at=invite.expires_at,
    )


async def active_membership(
    session: AsyncSession, member_tenant_id: uuid.UUID
) -> OrgMembership | None:
    return await session.scalar(
        select(OrgMembership).where(
            OrgMembership.member_tenant_id == member_tenant_id, OrgMembership.status == "active"
        )
    )


async def join(
    session: AsyncSession, code: str, user: User, tenant: Tenant, now: datetime
) -> OrgMembership:
    """Join the main account behind `code` with its current member template."""
    invite = await session.scalar(
        select(OrgInvite).where(OrgInvite.code_hash == hash_code(code), _open(now))
    )
    if invite is None:
        raise InviteInvalidError
    if invite.tenant_id == tenant.id:
        raise OwnInviteError
    if await active_membership(session, tenant.id) is not None:
        raise AlreadyMemberError
    # Taking a use is one conditional UPDATE, so two joiners can't both take the last.
    taken = await session.scalar(
        update(OrgInvite)
        .where(OrgInvite.id == invite.id, _open(now))
        .values(used_count=OrgInvite.used_count + 1)
        .returning(OrgInvite.id)
    )
    if taken is None:
        await session.rollback()
        raise InviteInvalidError
    sponsor = await session.get(Tenant, invite.tenant_id)
    assert sponsor is not None
    membership = OrgMembership(
        sponsor_tenant_id=sponsor.id,
        member_user_id=user.id,
        member_tenant_id=tenant.id,
        quotas=Quotas.model_validate(sponsor.member_default_quotas).model_dump(),
        invite_id=invite.id,
    )
    session.add(membership)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Another join for the same member won the race (Q65b's unique index).
        if "uq_org_memberships_active_member" in str(exc.orig):
            raise AlreadyMemberError from exc
        raise
    return membership


@dataclass(frozen=True)
class MemberRow:
    membership: OrgMembership
    user: User


async def list_members(session: AsyncSession, sponsor_tenant_id: uuid.UUID) -> list[MemberRow]:
    """Active members first, then past ones, newest first within each."""
    rows = await session.execute(
        select(OrgMembership, User)
        .join(User, User.id == OrgMembership.member_user_id)
        .where(OrgMembership.sponsor_tenant_id == sponsor_tenant_id)
        .order_by(
            case((OrgMembership.status == "active", 0), else_=1),
            OrgMembership.created_at.desc(),
        )
    )
    return [MemberRow(membership=m, user=u) for m, u in rows.all()]


async def sponsored_membership(
    session: AsyncSession, sponsor_tenant_id: uuid.UUID, membership_id: uuid.UUID
) -> OrgMembership | None:
    membership = await session.get(OrgMembership, membership_id)
    if membership is None or membership.sponsor_tenant_id != sponsor_tenant_id:
        return None
    return membership


async def set_quotas(session: AsyncSession, membership: OrgMembership, quotas: Quotas) -> None:
    membership.quotas = quotas.model_dump()
    await session.commit()


async def set_default_quotas(session: AsyncSession, tenant: Tenant, quotas: Quotas) -> None:
    tenant.member_default_quotas = quotas.model_dump()
    await session.commit()


async def end_membership(
    session: AsyncSession, membership: OrgMembership, status: str, now: datetime
) -> None:
    """The member left or was removed: their calls stop using the main account at once.

    Read-aloud audio the member had made on the main account's connection goes too,
    unless pinned (Q65h): it may say something from their replies.
    """
    if membership.status != "active":
        return
    membership.status = status
    membership.ended_at = now
    await session.execute(
        delete(TtsAudio).where(
            TtsAudio.tenant_id == membership.sponsor_tenant_id,
            TtsAudio.user_id == membership.member_user_id,
            TtsAudio.pinned.is_(False),
        )
    )
    await session.commit()
