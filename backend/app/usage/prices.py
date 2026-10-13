"""The tenant's own model prices (ADR 0034 §3): entered by the tenant, none built in."""

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelPrice
from app.usage.dashboard import Price

PRICE_FIELDS = ("input_per_mtok", "output_per_mtok", "per_kchar", "per_minute")


async def load_prices(session: AsyncSession, tenant_id: uuid.UUID) -> dict[tuple[str, str], Price]:
    rows = await session.scalars(select(ModelPrice).where(ModelPrice.tenant_id == tenant_id))
    return {
        (row.connection_name, row.model): Price(**{f: getattr(row, f) for f in PRICE_FIELDS})
        for row in rows
    }


async def replace_prices(
    session: AsyncSession, tenant_id: uuid.UUID, prices: Iterable[tuple[str, str, Price]]
) -> None:
    """The tenant's whole price list; a model with no price entered is dropped."""
    await session.execute(delete(ModelPrice).where(ModelPrice.tenant_id == tenant_id))
    session.add_all(
        ModelPrice(
            tenant_id=tenant_id,
            connection_name=connection,
            model=model,
            **{f: getattr(price, f) for f in PRICE_FIELDS},
        )
        for connection, model, price in prices
        if any(getattr(price, f) is not None for f in PRICE_FIELDS)
    )
