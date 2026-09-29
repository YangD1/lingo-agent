"""Business tables. LangGraph's checkpoint tables are managed by AsyncPostgresSaver.setup(),
not by Alembic."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampMixin

# Stored as CHECK-constrained strings rather than PG ENUM types: adding a value is a
# one-line migration instead of ALTER TYPE.
TENANT_KINDS = ("personal", "org")
MEMBER_ROLES = ("owner", "admin", "member")
PROVIDER_KINDS = ("deepseek", "anthropic", "openai", "openai_compatible")
ROUTE_SECTIONS = ("llm", "embedding", "asr")
USAGE_STATUSES = ("ok", "error")
ATTACHMENT_KINDS = ("image", "audio", "document")
ATTACHMENT_STATUSES = ("processing", "ready", "failed")
MEMORY_KINDS = ("fact", "episode")
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
EXPLANATION_LANGUAGES = ("zh", "en")


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
    # Chat model used when no route matches this tenant's connections (ADR 0007).
    default_model: Mapped[str | None] = mapped_column(String(128))
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
    # Speech-to-text is billed by audio length, not tokens; NULL when the vendor
    # doesn't report it (ADR 0008 §5).
    audio_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attachment(TimestampMixin, Base):
    """A file sent with a chat message (ADR 0008).

    Every attachment gets a plain-text rendering (`text`): image reading, audio
    transcript or extracted document text. The conversation, memory and RAG read that;
    the original bytes are only sent to a model on the turn they were attached to.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(_in("kind", ATTACHMENT_KINDS), name="kind"),
        CheckConstraint(_in("status", ATTACHMENT_STATUSES), name="status"),
        Index("ix_attachments_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_attachments_message_id", "message_id"),
        # Finds uploads that were never sent (the 24h cleanup).
        Index(
            "ix_attachments_unsent_created_at",
            "created_at",
            postgresql_where="message_id IS NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # Id of the HumanMessage in the LangGraph checkpoint; NULL until the message is sent.
    message_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    # Detected from the content, never taken from the client.
    mime_type: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Deferred: listing attachments must not pull megabytes of bytes.
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    text: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # User-safe reason; details stay in the server log.
    error: Mapped[str | None] = mapped_column(Text)


class UserProfile(TimestampMixin, Base):
    """What the tutor knows about a learner, as structured fields (ADR 0009 §1).

    Filled by the learner in the memory page and by post-turn reflection; reflection
    never overwrites a field listed in `manual_fields` (the learner's own edits win).
    """

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            f"cefr_level IS NULL OR {_in('cefr_level', CEFR_LEVELS)}", name="cefr_level"
        ),
        CheckConstraint(
            _in("explanation_language", EXPLANATION_LANGUAGES), name="explanation_language"
        ),
        CheckConstraint(
            "daily_minutes IS NULL OR daily_minutes BETWEEN 1 AND 600", name="daily_minutes"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    native_language: Mapped[str | None] = mapped_column(String(50))
    occupation: Mapped[str | None] = mapped_column(String(200))
    goal: Mapped[str | None] = mapped_column(Text)
    # e.g. "cet4", "ielts": the word book tags of ADR 0011.
    target_exam: Mapped[str | None] = mapped_column(String(20))
    interests: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default="{}"
    )
    daily_minutes: Mapped[int | None] = mapped_column(Integer)
    explanation_language: Mapped[str] = mapped_column(String(5), default="zh", server_default="zh")
    cefr_level: Mapped[str | None] = mapped_column(String(2))
    # IANA name; "today" for word reviews is cut in this zone.
    timezone: Mapped[str | None] = mapped_column(String(64))
    manual_fields: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), default=list, server_default="{}"
    )


class Memory(TimestampMixin, Base):
    """A long-term memory about a learner (ADR 0009 §1).

    `fact`: something true about the learner, all injected into the tutor's prompt.
    `episode`: the running summary of one conversation, retrieved by relevance.
    """

    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(_in("kind", MEMORY_KINDS), name="kind"),
        Index("ix_memories_user_id_kind_updated_at", "user_id", "kind", "updated_at"),
        # One running summary per conversation.
        Index(
            "uq_memories_episode_source_conversation_id",
            "source_conversation_id",
            unique=True,
            postgresql_where="kind = 'episode'",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # Kept when the conversation is deleted: the memory is the learner's to delete.
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    # No fixed dimension: tenants pick their own embedding model. Rows are compared only
    # with vectors of the same `embedding_model` ("<connection>:<model>"); each learner
    # has few enough memories that an exact scan needs no ANN index.
    embedding: Mapped[list[float] | None] = deferred(mapped_column(Vector()))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
