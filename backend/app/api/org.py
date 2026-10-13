"""Main accounts and members (ADR 0031): invites, joining, leaving, quotas.

The main account sees each member's name, email, dates and quotas, never their
learning data (Q65c); the member sees the main account's name.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.errors import api_error
from app.db.models import OrgInvite, OrgMembership, Tenant
from app.deps import CurrentTenant, CurrentUser, Manager, SessionDep, per_ip
from app.org import service, usage
from app.org.quotas import Capability, Quotas

router = APIRouter(prefix="/org", tags=["org"])

Code = Annotated[str, Field(min_length=1, max_length=100)]


class InviteOut(BaseModel):
    id: uuid.UUID
    expires_at: datetime
    max_uses: int | None
    used_count: int
    created_at: datetime


class InviteCreatedOut(InviteOut):
    # Shown once: only its hash is kept.
    code: str


class InviteIn(BaseModel):
    days: Annotated[int, Field(ge=1, le=service.MAX_INVITE_DAYS)] = service.DEFAULT_INVITE_DAYS
    # None: any number of people may join with it.
    max_uses: Annotated[int, Field(ge=1, le=1000)] | None = 1


class UsedOut(BaseModel):
    """In the capability's unit (`app.org.quotas.UNITS`): tokens, characters or minutes."""

    day: float
    month: float


Usage = dict[Capability, UsedOut]


def _usage(found: dict[Capability, usage.Used]) -> Usage:
    return {c: UsedOut(day=round(u.day, 2), month=round(u.month, 2)) for c, u in found.items()}


class MemberOut(BaseModel):
    id: uuid.UUID
    display_name: str | None
    email: str
    status: str
    joined_at: datetime
    ended_at: datetime | None
    quotas: Quotas
    # On this main account, today and this month (UTC).
    usage: Usage


class CodeIn(BaseModel):
    code: Code


class InvitePreviewOut(BaseModel):
    sponsor_name: str
    quotas: Quotas
    expires_at: datetime


class MembershipOut(BaseModel):
    sponsor_name: str
    joined_at: datetime
    quotas: Quotas
    usage: Usage


def _invite_out(invite: OrgInvite) -> InviteOut:
    return InviteOut.model_validate(invite, from_attributes=True)


async def _member_out(session: SessionDep, row: service.MemberRow) -> MemberOut:
    m = row.membership
    found = await usage.membership_use(session, m, datetime.now(UTC))
    return MemberOut(
        id=m.id,
        display_name=row.user.display_name,
        email=row.user.email,
        status=m.status,
        joined_at=m.created_at,
        ended_at=m.ended_at,
        quotas=Quotas.model_validate(m.quotas),
        usage=_usage(found),
    )


_INVITE_INVALID = api_error(
    status.HTTP_404_NOT_FOUND, "invite_invalid", "invite is unknown, expired, used up or revoked"
)
_NOT_FOUND = api_error(status.HTTP_404_NOT_FOUND, "not_found", "no such member")


# --- the main account ---------------------------------------------------------------


@router.get("/invites", dependencies=[Manager])
async def list_invites(session: SessionDep, tenant: CurrentTenant) -> list[InviteOut]:
    found = await service.open_invites(session, tenant.id, datetime.now(UTC))
    return [_invite_out(i) for i in found]


@router.post("/invites", dependencies=[Manager], status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteIn, session: SessionDep, user: CurrentUser, tenant: CurrentTenant
) -> InviteCreatedOut:
    invite, code = await service.create_invite(
        session, tenant.id, user.id, days=body.days, max_uses=body.max_uses, now=datetime.now(UTC)
    )
    return InviteCreatedOut(**_invite_out(invite).model_dump(), code=code)


@router.delete(
    "/invites/{invite_id}", dependencies=[Manager], status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_invite(invite_id: uuid.UUID, session: SessionDep, tenant: CurrentTenant) -> None:
    if not await service.revoke_invite(session, tenant.id, invite_id, datetime.now(UTC)):
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found", "no such invite")


@router.get("/members", dependencies=[Manager])
async def list_members(session: SessionDep, tenant: CurrentTenant) -> list[MemberOut]:
    return [
        await _member_out(session, row) for row in await service.list_members(session, tenant.id)
    ]


@router.put("/members/{membership_id}/quotas", dependencies=[Manager])
async def set_member_quotas(
    membership_id: uuid.UUID, body: Quotas, session: SessionDep, tenant: CurrentTenant
) -> MemberOut:
    membership = await service.sponsored_membership(session, tenant.id, membership_id)
    if membership is None or membership.status != "active":
        raise _NOT_FOUND
    await service.set_quotas(session, membership, body)
    rows = await service.list_members(session, tenant.id)
    return await _member_out(session, next(r for r in rows if r.membership.id == membership_id))


@router.delete(
    "/members/{membership_id}", dependencies=[Manager], status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    membership_id: uuid.UUID, session: SessionDep, tenant: CurrentTenant
) -> None:
    membership = await service.sponsored_membership(session, tenant.id, membership_id)
    if membership is None or membership.status != "active":
        raise _NOT_FOUND
    await service.end_membership(session, membership, "removed", datetime.now(UTC))


@router.get("/default-quotas", dependencies=[Manager])
async def get_default_quotas(tenant: CurrentTenant) -> Quotas:
    return Quotas.model_validate(tenant.member_default_quotas)


@router.put("/default-quotas", dependencies=[Manager])
async def set_default_quotas(body: Quotas, session: SessionDep, tenant: CurrentTenant) -> Quotas:
    await service.set_default_quotas(session, tenant, body)
    return body


# --- the member ---------------------------------------------------------------------


@router.post("/join/preview", dependencies=[per_ip("signup")])
async def preview_join(body: CodeIn, session: SessionDep, user: CurrentUser) -> InvitePreviewOut:
    try:
        found = await service.preview_invite(session, body.code, datetime.now(UTC))
    except service.InviteInvalidError as exc:
        raise _INVITE_INVALID from exc
    return InvitePreviewOut(
        sponsor_name=found.sponsor.name, quotas=found.quotas, expires_at=found.expires_at
    )


@router.post("/join", status_code=status.HTTP_201_CREATED, dependencies=[per_ip("signup")])
async def join(
    body: CodeIn, session: SessionDep, user: CurrentUser, tenant: CurrentTenant
) -> MembershipOut:
    try:
        membership = await service.join(session, body.code, user, tenant, datetime.now(UTC))
    except service.InviteInvalidError as exc:
        raise _INVITE_INVALID from exc
    except service.OwnInviteError as exc:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "own_invite", "this invite is your own"
        ) from exc
    except service.AlreadyMemberError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, "already_member", "leave your current main account first"
        ) from exc
    return await _membership_out(session, membership)


@router.get("/membership")
async def my_membership(session: SessionDep, tenant: CurrentTenant) -> MembershipOut | None:
    membership = await service.active_membership(session, tenant.id)
    return None if membership is None else await _membership_out(session, membership)


@router.delete("/membership", status_code=status.HTTP_204_NO_CONTENT)
async def leave(session: SessionDep, tenant: CurrentTenant) -> None:
    membership = await service.active_membership(session, tenant.id)
    if membership is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found", "not a member")
    await service.end_membership(session, membership, "left", datetime.now(UTC))


async def _membership_out(session: SessionDep, membership: OrgMembership) -> MembershipOut:
    sponsor = await session.get(Tenant, membership.sponsor_tenant_id)
    assert sponsor is not None
    return MembershipOut(
        sponsor_name=sponsor.name,
        joined_at=membership.created_at,
        quotas=Quotas.model_validate(membership.quotas),
        usage=_usage(await usage.membership_use(session, membership, datetime.now(UTC))),
    )
