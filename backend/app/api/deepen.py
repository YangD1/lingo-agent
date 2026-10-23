"""The tenant's limits on the tutor's follow-up segments (ADR 0064 §5)."""

from fastapi import APIRouter

from app.chat.deepen import DeepenSettings, deepen_settings
from app.deps import CurrentTenant, Manager, SessionDep

router = APIRouter(tags=["chat"])


@router.get("/tenant/deepen", dependencies=[Manager])
async def tenant_deepen(tenant: CurrentTenant) -> DeepenSettings:
    return deepen_settings(tenant.deepen_settings)


@router.put("/tenant/deepen", dependencies=[Manager])
async def set_tenant_deepen(
    body: DeepenSettings, tenant: CurrentTenant, session: SessionDep
) -> DeepenSettings:
    tenant.deepen_settings = body.model_dump()
    await session.commit()
    return body
