from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import InvalidTokenError, decode_access_token
from app.auth.service import get_personal_tenant
from app.db.models import Tenant, TenantMember, User
from app.settings import Settings, get_settings

AUTH_COOKIE = "lingo_access_token"

# Bearer is for non-browser clients (curl, tests, Swagger's Authorize button);
# the browser uses the httpOnly cookie (ADR 0003).
_bearer = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    bearer_token: Annotated[str | None, Depends(_bearer)],
) -> User:
    token = bearer_token or request.cookies.get(AUTH_COOKIE)
    if not token:
        raise _unauthorized()
    try:
        user_id = decode_access_token(token, settings)
    except InvalidTokenError as exc:
        raise _unauthorized() from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_tenant(user: CurrentUser, session: SessionDep) -> Tenant:
    """P0: every user acts in their personal tenant (ADR 0004)."""
    tenant = await get_personal_tenant(session, user.id)
    if tenant is None:  # registration creates it atomically, so this is data corruption
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "personal tenant missing")
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]


async def require_tenant_manager(
    user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> None:
    member = await session.get(TenantMember, (tenant.id, user.id))
    if member is None or member.role not in ("owner", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only tenant owners/admins can do this")


# Route dependency: `dependencies=[Manager]`.
Manager = Depends(require_tenant_manager)
