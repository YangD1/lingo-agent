import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import connection_aad, get_keyring
from app.db.models import ProviderConnection, Tenant, TenantModelRoute
from app.providers.tenant import load_provider_context


async def _tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(name="t", kind="personal")
    session.add(tenant)
    await session.flush()
    return tenant


def _connection(tenant: Tenant, name: str, key: str | None, **kw: object) -> ProviderConnection:
    conn_id = uuid.uuid4()
    encrypted = get_keyring().encrypt(key, connection_aad(tenant.id, conn_id)) if key else None
    return ProviderConnection(
        id=conn_id,
        tenant_id=tenant.id,
        name=name,
        kind=kw.pop("kind", name),
        base_url=kw.pop("base_url", f"https://{name}.example.com/v1"),
        encrypted_api_key=encrypted,
        **kw,
    )


async def test_loads_and_decrypts_connections_and_routes(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    db_session.add_all(
        [
            _connection(tenant, "deepseek", "sk-ds", params={"timeout": 60}),
            _connection(tenant, "local", None, kind="openai_compatible"),
            TenantModelRoute(
                tenant_id=tenant.id, section="llm", task="chat", models=["deepseek:deepseek-chat"]
            ),
        ]
    )
    await db_session.commit()

    ctx = await load_provider_context(db_session, tenant.id)
    assert set(ctx.connections) == {"deepseek", "local"}
    deepseek = ctx.connections["deepseek"]
    assert deepseek.api_key is not None and deepseek.api_key.get_secret_value() == "sk-ds"
    assert deepseek.params == {"timeout": 60}
    assert ctx.connections["local"].api_key is None
    assert ctx.routes[("llm", "chat")].models == ["deepseek:deepseek-chat"]


async def test_disabled_and_undecryptable_connections_are_skipped(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    other = await _tenant(db_session)
    good = _connection(tenant, "openai", "sk-good")
    disabled = _connection(tenant, "deepseek", "sk-off", enabled=False)
    # Ciphertext bound to another tenant's row, copied here: must not decrypt.
    stolen = _connection(other, "anthropic", "sk-stolen")
    stolen.tenant_id = tenant.id
    db_session.add_all([good, disabled, stolen])
    await db_session.commit()

    ctx = await load_provider_context(db_session, tenant.id)
    assert set(ctx.connections) == {"openai"}


async def test_version_changes_when_config_changes(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    conn = _connection(tenant, "openai", "sk-1")
    db_session.add(conn)
    await db_session.commit()
    v1 = (await load_provider_context(db_session, tenant.id)).version
    assert (await load_provider_context(db_session, tenant.id)).version == v1  # stable

    conn.params = {"timeout": 5}
    await db_session.commit()
    v2 = (await load_provider_context(db_session, tenant.id)).version
    assert v2 != v1

    db_session.add(
        TenantModelRoute(tenant_id=tenant.id, section="llm", task="chat", models=["openai:m"])
    )
    await db_session.commit()
    assert (await load_provider_context(db_session, tenant.id)).version not in (v1, v2)
