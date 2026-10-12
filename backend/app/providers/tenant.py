"""Load a tenant's provider connections and routes into a TenantProviderContext."""

import hashlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import DecryptError, Keyring, connection_aad, get_keyring
from app.db.models import ProviderConnection, Tenant, TenantModelRoute, TutorProfile
from app.org.service import active_membership
from app.org.usage import exhausted_sections
from app.providers.config import (
    ConnectionSpec,
    ProviderKind,
    RouteSpec,
    Sponsor,
    TenantProviderContext,
    TutorPick,
)

logger = logging.getLogger(__name__)


async def load_provider_context(
    session: AsyncSession, tenant_id: uuid.UUID, keyring: Keyring | None = None
) -> TenantProviderContext:
    """The tenant's connections and routes, and its main account's when it is a member
    (ADR 0031 §5). Quotas are checked here, once per load (§6)."""
    keyring = keyring or get_keyring()
    own = await _with_tutor(session, await _load(session, tenant_id, keyring))
    membership = await active_membership(session, tenant_id)
    if membership is None:
        return own
    lent = await _load(session, membership.sponsor_tenant_id, keyring)
    sponsor_tenant = await session.get(Tenant, membership.sponsor_tenant_id)
    assert sponsor_tenant is not None  # FK, cascade
    exhausted = await exhausted_sections(session, membership, datetime.now(UTC))
    return replace(
        own,
        version=f"{own.version}:{lent.version}",
        sponsor=Sponsor(ctx=lent, name=sponsor_tenant.name, exhausted=exhausted),
    )


async def _with_tutor(session: AsyncSession, ctx: TenantProviderContext) -> TenantProviderContext:
    """The learner's own tutor picks (ADR 0032 §3). A personal tenant has one learner;
    the picks are part of the version, so cached models follow a change."""
    profile = await session.scalar(
        select(TutorProfile).where(TutorProfile.tenant_id == ctx.tenant_id).limit(1)
    )
    if profile is None:
        return ctx
    tutor = TutorPick(
        name=profile.name,
        chat_model=profile.chat_model,
        tts_model=profile.tts_model,
        voices=dict(profile.voices),
        realtime_model=profile.realtime_model,
        realtime_voice=profile.realtime_voice,
    )
    return replace(ctx, tutor=tutor, version=f"{ctx.version}:t{profile.updated_at.isoformat()}")


async def _load(
    session: AsyncSession, tenant_id: uuid.UUID, keyring: Keyring
) -> TenantProviderContext:
    connections = (
        await session.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.tenant_id == tenant_id)
            # Creation order is the auto-fallback order (ADR 0007 §3).
            .order_by(ProviderConnection.created_at, ProviderConnection.id)
        )
    ).all()
    routes = (
        await session.scalars(
            select(TenantModelRoute).where(TenantModelRoute.tenant_id == tenant_id)
        )
    ).all()

    specs: dict[str, ConnectionSpec] = {}
    for conn in connections:
        if not conn.enabled:
            continue
        api_key: SecretStr | None = None
        if conn.encrypted_api_key is not None:
            try:
                api_key = SecretStr(
                    keyring.decrypt(conn.encrypted_api_key, connection_aad(tenant_id, conn.id))
                )
            except DecryptError:
                # Unusable (key removed from keyring, or row tampered with): skip it so
                # the rest of the chain still works, and make it visible in logs.
                logger.error(
                    "cannot decrypt provider connection %s of tenant %s", conn.id, tenant_id
                )
                continue
        kind: ProviderKind = conn.kind  # type: ignore[assignment]  # DB CHECK constraint
        specs[conn.name] = ConnectionSpec(
            name=conn.name,
            kind=kind,
            base_url=conn.base_url,
            api_key=api_key,
            params=conn.params,
            default_model=conn.default_model,
        )

    return TenantProviderContext(
        tenant_id=tenant_id,
        connections=specs,
        routes={
            (r.section, r.task): RouteSpec(models=r.models, params=r.params, disabled=r.disabled)
            for r in routes
        },
        version=_fingerprint(connections, routes),
    )


def _fingerprint(
    connections: Sequence[ProviderConnection], routes: Sequence[TenantModelRoute]
) -> str:
    """Changes whenever a row is added, removed or updated (updated_at has onupdate)."""
    rows = sorted(
        [f"c:{c.id}:{c.updated_at.isoformat()}" for c in connections]
        + [f"r:{r.id}:{r.updated_at.isoformat()}" for r in routes]
    )
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]
