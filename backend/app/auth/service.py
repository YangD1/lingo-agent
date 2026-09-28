import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import burn_verify_time, hash_password, verify_password
from app.db.models import Tenant, TenantMember, User


class EmailTakenError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def register_user(
    session: AsyncSession, email: str, password: str, display_name: str | None = None
) -> User:
    """Create a user with their personal tenant and owner membership, atomically."""
    email = normalize_email(email)
    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    tenant = Tenant(name=display_name or email.split("@", 1)[0], kind="personal")
    session.add_all([user, tenant])
    try:
        await session.flush()
        session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # The unique index is the source of truth; checking first would race.
        if "uq_users_email" in str(exc.orig):
            raise EmailTakenError(email) from exc
        raise
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        burn_verify_time(password)
        return None
    ok, new_hash = verify_password(password, user.password_hash)
    if not ok or not user.is_active:
        return None
    if new_hash is not None:
        user.password_hash = new_hash
        await session.commit()
    return user


async def get_personal_tenant(session: AsyncSession, user_id: uuid.UUID) -> Tenant | None:
    return await session.scalar(
        select(Tenant)
        .join(TenantMember, TenantMember.tenant_id == Tenant.id)
        .where(
            TenantMember.user_id == user_id,
            TenantMember.role == "owner",
            Tenant.kind == "personal",
        )
    )
