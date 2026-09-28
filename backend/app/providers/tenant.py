"""Load a tenant's provider connections and routes into a TenantProviderContext."""

import hashlib
import logging
import uuid
from collections.abc import Sequence

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import DecryptError, Keyring, connection_aad, get_keyring
from app.db.models import ProviderConnection, TenantModelRoute
from app.providers.config import ConnectionSpec, ProviderKind, RouteSpec, TenantProviderContext

logger = logging.getLogger(__name__)


async def load_provider_context(
    session: AsyncSession, tenant_id: uuid.UUID, keyring: Keyring | None = None
) -> TenantProviderContext:
    keyring = keyring or get_keyring()
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
        routes={(r.section, r.task): RouteSpec(models=r.models, params=r.params) for r in routes},
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
