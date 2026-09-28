"""Re-encrypt stored credentials with the primary key: `python -m app.credentials.rotate`.

Rotation procedure (ADR 0004 §3):
1. Prepend a new key to CREDENTIALS_ENCRYPTION_KEYS (`make gen-key`) and restart.
2. Run this command.
3. Remove the old key from CREDENTIALS_ENCRYPTION_KEYS and restart.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import Keyring, connection_aad, get_keyring
from app.db.models import ProviderConnection
from app.db.session import create_engine, create_sessionmaker
from app.settings import get_settings


async def rotate_credentials(session: AsyncSession, keyring: Keyring) -> int:
    """Returns how many rows were re-encrypted. Idempotent."""
    rotated = 0
    rows = await session.scalars(
        select(ProviderConnection).where(ProviderConnection.encrypted_api_key.is_not(None))
    )
    for conn in rows:
        assert conn.encrypted_api_key is not None
        if not keyring.needs_rotation(conn.encrypted_api_key):
            continue
        aad = connection_aad(conn.tenant_id, conn.id)
        conn.encrypted_api_key = keyring.encrypt(keyring.decrypt(conn.encrypted_api_key, aad), aad)
        rotated += 1
    await session.commit()
    return rotated


async def _main() -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            count = await rotate_credentials(session, get_keyring())
    finally:
        await engine.dispose()
    print(f"re-encrypted {count} credential(s) with key {get_keyring().primary_id!r}")


if __name__ == "__main__":
    asyncio.run(_main())
