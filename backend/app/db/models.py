"""Business tables. LangGraph's checkpoint tables are managed by AsyncPostgresSaver.setup(),
not by Alembic."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Stored as CHECK-constrained strings rather than PG ENUM types: adding a value is a
# one-line migration instead of ALTER TYPE.
TENANT_KINDS = ("personal", "org")
MEMBER_ROLES = ("owner", "admin", "member")
PROVIDER_KINDS = ("deepseek", "anthropic", "openai", "openai_compatible")
ROUTE_SECTIONS = ("llm", "embedding")
USAGE_STATUSES = ("ok", "error")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint(_in("kind", TENANT_KINDS), name="kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Always stored lower-cased by the auth service; unique index enforces one account.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class TenantMember(Base):
    __tablename__ = "tenant_members"
    __table_args__ = (CheckConstraint(_in("role", MEMBER_ROLES), name="role"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(TimestampMixin, Base):
    """One chat thread; its id is the LangGraph thread_id."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")


class ProviderConnection(TimestampMixin, Base):
    """A tenant's connection to a model vendor (ADR 0004). The API key is encrypted."""

    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint(_in("kind", PROVIDER_KINDS), name="kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    # Route model refs use "<name>:<model>"; defaults to the preset name it was created from.
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    # Always explicit (filled from the preset on creation): SDKs would otherwise fall
    # back to env vars like OPENAI_BASE_URL.
    base_url: Mapped[str] = mapped_column(String(500))
    # AES-GCM ciphertext "v1:<key_id>:<nonce>:<ct>"; None for keyless endpoints.
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    key_hint: Mapped[str | None] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class TenantModelRoute(TimestampMixin, Base):
    """A tenant's override of the default route for one task (ADR 0004)."""

    __tablename__ = "tenant_model_routes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "section", "task"),
        CheckConstraint(_in("section", ROUTE_SECTIONS), name="section"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    section: Mapped[str] = mapped_column(String(20))
    task: Mapped[str] = mapped_column(String(64))
    # Ordered "<connection name>:<model>" refs: primary first, then fallbacks.
    models: Mapped[list[str]] = mapped_column(JSONB)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class LLMUsage(Base):
    """One model call's metadata (ADR 0005). Never stores prompt or completion content."""

    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_tenant_id_created_at", "tenant_id", "created_at"),
        CheckConstraint(_in("status", USAGE_STATUSES), name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # No FK: usage history outlives deleted conversations.
    conversation_id: Mapped[uuid.UUID | None]
    task: Mapped[str] = mapped_column(String(64))
    connection_name: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))
    # True when this model served the call because an earlier model in the chain failed.
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
