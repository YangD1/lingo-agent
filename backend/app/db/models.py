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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.adaptive.exercise.formats import FORMATS
from app.adaptive.kc.catalog import ERROR_TYPES
from app.adaptive.rules import EVIDENCE_KINDS, SEVERITIES
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
KC_KINDS = ("grammar", "word")
EVIDENCE_SOURCES = ("chat", "placement", "exercise", "writing", "reading")
SKILLS = ("listening", "speaking", "reading", "writing", "grammar", "vocab")
ACTIVITY_KINDS = ("step", "tool", "mcp", "background")
ACTIVITY_STATUSES = ("ok", "failed", "skipped")
CARD_SOURCES = ("book", "auto", "manual", "placement")
CARD_STATUSES = ("new", "learning", "known", "suspended")
PLACEMENT_STATUSES = ("in_progress", "done", "abandoned")
PLACEMENT_STAGES = ("vocab", "grammar")
# planning: after a placement test (ADR 0015 §6); daily: the dashboard's (ADR 0016).
CONVERSATION_PURPOSES = ("planning", "daily")
TUTOR_CARD_KINDS = ("word_book", "learning_goal", "practice", "link")
# proposed -> applied | declined; applied -> undone. Cards without side effects: info.
TUTOR_CARD_STATUSES = ("proposed", "applied", "declined", "undone", "info")
# Where a practice set was started from (ADR 0021); prefetch: made in the background
# after the learner finished a set, waiting for the next one.
EXERCISE_SET_ORIGINS = ("dashboard", "learner", "card", "plan", "practice", "prefetch")
# generating -> ready -> in_progress -> done; generating -> failed.
EXERCISE_SET_STATUSES = ("generating", "ready", "in_progress", "done", "failed")
# rejected: kept for the record, never shown; reported: the learner flagged it, so its
# answers count as no evidence.
EXERCISE_STATUSES = ("ok", "rejected", "reported")


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
    __table_args__ = (
        Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),
        CheckConstraint(_in("purpose", CONVERSATION_PURPOSES), name="purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # Post-turn reflection cursors (ADR 0009 §3): ids of the last messages already
    # reflected on / folded into the conversation summary. NULL: none yet.
    reflected_message_id: Mapped[str | None] = mapped_column(String(64))
    summarized_message_id: Mapped[str | None] = mapped_column(String(64))
    # Grammar KC this conversation practises (P1 plan §7.5.3); NULL for free chat. No FK:
    # the catalog is a file, so the id is checked against it when the row is written.
    focus_kc_id: Mapped[str | None] = mapped_column(String(64))
    # What the conversation is for, besides practice (ADR 0015 §6): "planning" is the
    # study-planning conversation started from the placement result; NULL for free chat.
    purpose: Mapped[str | None] = mapped_column(String(20))


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
        # The learner dashboard counts chat turns per day from here.
        Index("ix_llm_usage_user_id_created_at", "user_id", "created_at"),
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
            f"explanation_language IS NULL OR {_in('explanation_language', EXPLANATION_LANGUAGES)}",
            name="explanation_language",
        ),
        CheckConstraint(
            "daily_minutes IS NULL OR daily_minutes BETWEEN 1 AND 600", name="daily_minutes"
        ),
        CheckConstraint(
            f"chat_language IS NULL OR {_in('chat_language', EXPLANATION_LANGUAGES)}",
            name="chat_language",
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
    # Language for grammar explanations; NULL until the learner (or reflection) says.
    explanation_language: Mapped[str | None] = mapped_column(String(5))
    # Which language the tutor mainly talks in (ADR 0017 §1); NULL: picked by level
    # (app/memory/language.py). Only the learner sets it.
    chat_language: Mapped[str | None] = mapped_column(String(5))
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


class KCEvidence(Base):
    """One observation about a learner's grasp of one KC; append-only (ADR 0012 §2).

    The source of truth for mastery: kc_mastery is rebuilt by replaying these rows, and
    severity or per-turn rules apply at replay time, so nothing is filtered on write.
    Rows with `correct = false` are the learner's mistakes and carry their details.
    """

    __tablename__ = "kc_evidence"
    __table_args__ = (
        CheckConstraint(_in("evidence", EVIDENCE_KINDS), name="evidence"),
        CheckConstraint(_in("source", EVIDENCE_SOURCES), name="source"),
        CheckConstraint(
            f"error_type IS NULL OR {_in('error_type', ERROR_TYPES)}", name="error_type"
        ),
        CheckConstraint(f"severity IS NULL OR {_in('severity', SEVERITIES)}", name="severity"),
        CheckConstraint(f"format IS NULL OR {_in('format', FORMATS)}", name="format"),
        # Practice answers always say which format they came from; nothing else does.
        CheckConstraint("(source = 'exercise') = (format IS NOT NULL)", name="format_source"),
        # A mistake always says how and how badly; a success never does.
        CheckConstraint(
            "correct = (error_type IS NULL) AND correct = (severity IS NULL)", name="mistake_fields"
        ),
        Index("ix_kc_evidence_user_id_created_at", "user_id", "created_at"),
        Index("ix_kc_evidence_user_id_kc_id_created_at", "user_id", "kc_id", "created_at"),
        Index("ix_kc_evidence_attempt_id", "attempt_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # No FK: KC ids come from the checked-in catalog (grammar.yaml) or `w.<lemma>`.
    kc_id: Mapped[str] = mapped_column(String(100))
    correct: Mapped[bool] = mapped_column(Boolean)
    evidence: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    # Kept when the conversation is deleted: evidence is the learner's to delete.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    # The learner message it came from (LangGraph message id); the per-turn cap of
    # rules.yaml groups by it. NULL for placement answers.
    message_id: Mapped[str | None] = mapped_column(String(64))
    error_type: Mapped[str | None] = mapped_column(String(20))
    severity: Mapped[str | None] = mapped_column(String(10))
    original: Mapped[str | None] = mapped_column(Text)
    correction: Mapped[str | None] = mapped_column(Text)
    # The error mirrors a pattern of the learner's first language.
    l1_transfer: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Practice answers (source `exercise`): the item's format and the answer itself.
    # One find_fix answer gives two rows, recognition and production (ADR 0021 §1).
    format: Mapped[str | None] = mapped_column(String(20))
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KCMastery(TimestampMixin, Base):
    """Cached result of replaying a learner's evidence for one KC (ADR 0012 §2).

    Rows whose `rules_version` differs from rules.yaml are stale and get rebuilt. The
    "learned" progress and the FSRS columns are replayed from evidence too (ADR 0021
    §7): the FSRS state is set once the KC is learned and mirrors `fsrs.Card` like
    `user_cards`.
    """

    __tablename__ = "kc_mastery"
    __table_args__ = (
        CheckConstraint(_in("kind", KC_KINDS), name="kind"),
        CheckConstraint("p_mastery BETWEEN 0 AND 1", name="p_mastery"),
        CheckConstraint("state IS NULL OR state BETWEEN 1 AND 3", name="state"),
        CheckConstraint("(mastered_at IS NULL) = (due IS NULL)", name="mastered_due"),
        # Learned grammar points coming due for review.
        Index(
            "ix_kc_mastery_user_id_due",
            "user_id",
            "due",
            postgresql_where="due IS NOT NULL",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kc_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    p_mastery: Mapped[float] = mapped_column(Float)
    # Counted observations only (after the severity and per-turn rules).
    observations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recog_correct: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    produce_correct: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rules_version: Mapped[str] = mapped_column(String(50))
    # Progress towards "learned" (rules.yaml mastery_gate): formats answered correctly
    # in practice, hours between the first and the last correct practice answer, and
    # the latest counted mistake in conversation or writing.
    formats_passed: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default="{}"
    )
    correct_span_hours: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    last_mistake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The evidence time at which all conditions first held.
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # fsrs.State: 1 learning, 2 review, 3 relearning.
    state: Mapped[int | None] = mapped_column(SmallInteger)
    step: Mapped[int | None] = mapped_column(SmallInteger)
    stability: Mapped[float | None] = mapped_column(Float)
    difficulty: Mapped[float | None] = mapped_column(Float)
    due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_review: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillEstimate(TimestampMixin, Base):
    """Elo ability per skill (ADR 0010 §2). Uncertainty is K(attempts), not stored."""

    __tablename__ = "skill_estimates"
    __table_args__ = (
        CheckConstraint(_in("skill", SKILLS), name="skill"),
        CheckConstraint("attempts >= 0", name="attempts"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    skill: Mapped[str] = mapped_column(String(20), primary_key=True)
    rating: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class MessageTranslation(Base):
    """A tutor message in the other language, made when the learner asked (ADR 0017 §4).

    Kept so switching back and forth calls no model; deleted with the conversation.
    """

    __tablename__ = "message_translations"
    __table_args__ = (CheckConstraint(_in("target", EXPLANATION_LANGUAGES), name="target"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    # The message id the conversation's history shows (the last part of a reply).
    message_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    target: Mapped[str] = mapped_column(String(5), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TutorCard(Base):
    """A card the tutor put in the conversation with a tool call (ADR 0015 §4).

    Tools only write these rows; learner data changes when the learner applies a
    proposal, and `before` keeps what it replaced so the change can be undone. Cards
    are the source of truth for what the conversation shows: their status changes
    outside the conversation, so it can't live in the checkpoint.
    """

    __tablename__ = "tutor_cards"
    __table_args__ = (
        CheckConstraint(_in("kind", TUTOR_CARD_KINDS), name="kind"),
        CheckConstraint(_in("status", TUTOR_CARD_STATUSES), name="status"),
        # A retried tools node finds its card instead of writing a second one.
        UniqueConstraint("conversation_id", "tool_call_id"),
        Index("ix_tutor_cards_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # The learner message that started the turn, as in agent_activities.
    turn_id: Mapped[str] = mapped_column(String(64))
    tool_call_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10))
    # What applying replaced; NULL until applied.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentActivity(Base):
    """One thing the tutor did on a turn, shown to the learner (ADR 0013 §3).

    A turn is keyed by the learner message that started it. Writing the same step again
    (a retried reflection) replaces its row. `summary` holds only the whitelisted fields
    of `app.activity` - counts, KC ids, memory ids - never prompts or model output, and
    memories by reference, so one the learner deletes leaves no copy here.
    """

    __tablename__ = "agent_activities"
    __table_args__ = (
        CheckConstraint(_in("kind", ACTIVITY_KINDS), name="kind"),
        CheckConstraint(_in("status", ACTIVITY_STATUSES), name="status"),
        UniqueConstraint("conversation_id", "turn_id", "name", "call_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Deleted with the conversation: summaries quote the learner's own messages.
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    turn_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(50))
    # Tells apart repeated calls of one tool in a turn; empty for fixed steps.
    call_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    status: Mapped[str] = mapped_column(String(10))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Word(Base):
    """A dictionary entry: global read-only data imported from ECDICT (ADR 0011).

    Not per tenant or user; learners' cards point here. Rows are only added or
    updated by the importer, never deleted, since cards may refer to them.
    """

    __tablename__ = "words"
    __table_args__ = (
        CheckConstraint("collins BETWEEN 0 AND 5", name="collins"),
        # Word books are the words carrying a tag (task 11).
        Index("ix_words_tags", "tags", postgresql_using="gin"),
        # New words come in order of frequency.
        Index("ix_words_frq", "frq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Case kept: ECDICT lists "US" and "us" separately.
    word: Mapped[str] = mapped_column(String(100), unique=True)
    phonetic: Mapped[str | None] = mapped_column(String(100))
    # Chinese glosses, one part of speech per line.
    translation: Mapped[str] = mapped_column(Text)
    # English definitions (WordNet), when present.
    definition: Mapped[str | None] = mapped_column(Text)
    # Collins stars, 0 = none.
    collins: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    # In the Oxford 3000 core vocabulary.
    oxford: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Exam lists: zk gk cet4 cet6 ky toefl ielts gre.
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(10)), default=list, server_default="{}")
    # Frequency ranks (British National Corpus, contemporary corpus); None = unranked.
    bnc: Mapped[int | None] = mapped_column(Integer)
    frq: Mapped[int | None] = mapped_column(Integer)
    # Inflections as ECDICT writes them, e.g. "p:went/d:gone/0:go"; "0:" is the lemma.
    exchange: Mapped[str | None] = mapped_column(String(300))


class WordExample(Base):
    """Example sentences a model wrote for a word at a level (ADR 0017 §3).

    Shared by a tenant's learners (they only depend on the word and the level), not
    across tenants: each pays for its own model calls.
    """

    __tablename__ = "word_examples"
    __table_args__ = (CheckConstraint(_in("cefr", CEFR_LEVELS), name="cefr"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), primary_key=True)
    cefr: Mapped[str] = mapped_column(String(2), primary_key=True)
    # [{"en": ..., "zh": ...}], each checked to use the word or one of its forms.
    sentences: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WordSentence(Base):
    """A real example sentence for a word, with its Chinese translation (ADR 0020).

    Global read-only data like `words`, imported from Tatoeba by
    `make sentences-import`; nothing refers to these rows, so a new import replaces
    all of a source's rows.
    """

    __tablename__ = "word_sentences"

    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    # 0 = the best sentence for the word.
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    en: Mapped[str] = mapped_column(Text)
    zh: Mapped[str] = mapped_column(Text)
    # The sentence's id at the source, for linking back to it (Tatoeba: the English one).
    source_id: Mapped[str] = mapped_column(String(40))


class UserWordBook(TimestampMixin, Base):
    """The word book a learner is working through; one at a time (ADR 0011).

    Books are defined in code (`app.services.vocab.books`). Switching books keeps all
    progress: cards belong to words, not books.
    """

    __tablename__ = "user_word_book"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    book_id: Mapped[str] = mapped_column(String(20))
    # New words a day; None = the default in rules.yaml.
    daily_new: Mapped[int | None] = mapped_column(SmallInteger)
    # Known-word screening: where in the book's frequency order the next batch starts.
    screen_offset: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class UserCard(TimestampMixin, Base):
    """A learner's card for one word, with its FSRS state (ADR 0011).

    Book words get a card when first reviewed or screened; words the learner or the
    tutor adds get one at once (status `new`). The FSRS columns mirror
    `fsrs.Card.to_dict()` and are set only while the word is being learned; `known`
    words are never scheduled.
    """

    __tablename__ = "user_cards"
    __table_args__ = (
        CheckConstraint(_in("source", CARD_SOURCES), name="source"),
        CheckConstraint(_in("status", CARD_STATUSES), name="status"),
        CheckConstraint("state IS NULL OR state BETWEEN 1 AND 3", name="state"),
        CheckConstraint("status <> 'learning' OR due IS NOT NULL", name="learning_due"),
        UniqueConstraint("user_id", "word_id"),
        # Due reviews.
        Index(
            "ix_user_cards_user_id_due",
            "user_id",
            "due",
            postgresql_where="status = 'learning'",
        ),
        # "New words started today".
        Index("ix_user_cards_user_id_first_reviewed_at", "user_id", "first_reviewed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    source: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    # fsrs.State: 1 learning, 2 review, 3 relearning.
    state: Mapped[int | None] = mapped_column(SmallInteger)
    step: Mapped[int | None] = mapped_column(SmallInteger)
    stability: Mapped[float | None] = mapped_column(Float)
    difficulty: Mapped[float | None] = mapped_column(Float)
    due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_review: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewLog(Base):
    """One review of a card, with its FSRS state before and after, so parameters can
    be fitted per learner later (ADR 0011, P4)."""

    __tablename__ = "review_logs"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 4", name="rating"),
        Index("ix_review_logs_user_id_reviewed_at", "user_id", "reviewed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("user_cards.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # fsrs.Rating: 1 again, 2 hard, 3 good, 4 easy.
    rating: Mapped[int] = mapped_column(SmallInteger)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_duration_ms: Mapped[int | None] = mapped_column(Integer)
    card_before: Mapped[dict[str, Any]] = mapped_column(JSONB)
    card_after: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PlacementSession(TimestampMixin, Base):
    """One run of the placement test (P1 plan §6.2); its id is the LangGraph thread id.

    The answers live in the checkpoint while the test runs; when it ends they are
    copied into `result` with the estimates, and the thread is deleted.
    """

    __tablename__ = "placement_sessions"
    __table_args__ = (
        CheckConstraint(_in("status", PLACEMENT_STATUSES), name="status"),
        CheckConstraint(_in("stage", PLACEMENT_STAGES), name="stage"),
        CheckConstraint("(status = 'done') = (result IS NOT NULL)", name="done_result"),
        # One test at a time per learner.
        Index(
            "uq_placement_sessions_user_id_in_progress",
            "user_id",
            unique=True,
            postgresql_where="status = 'in_progress'",
        ),
        Index("ix_placement_sessions_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(12))
    stage: Mapped[str] = mapped_column(String(10))
    # Drives word sampling, pseudo-word positions and option order, so a resumed test
    # shows the same question it stopped at.
    seed: Mapped[int] = mapped_column(BigInteger)
    rules_version: Mapped[str] = mapped_column(String(50))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlacementItemStat(TimestampMixin, Base):
    """Calibrated difficulty of one grammar item (ADR 0012 §3); global, not per tenant.

    Starts from the rubric prior and is updated after each finished test with that
    test's final ability, never mid-test. The test switches to it only once an item
    has enough answers (rules.yaml).
    """

    __tablename__ = "placement_item_stats"
    __table_args__ = (CheckConstraint("attempts >= 0", name="attempts"),)

    item_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    difficulty: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ExerciseSet(Base):
    """One practice set: the planned KCs and formats, then its items (ADR 0021 §3)."""

    __tablename__ = "exercise_sets"
    __table_args__ = (
        CheckConstraint(_in("origin", EXERCISE_SET_ORIGINS), name="origin"),
        CheckConstraint(_in("status", EXERCISE_SET_STATUSES), name="status"),
        Index("ix_exercise_sets_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    # The planner's output: one entry per item (KC, format, target difficulty).
    kc_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # rules.yaml version it was planned under: a set generated ahead of time is
    # replanned when the rules changed since (Q33e).
    rules_version: Mapped[str] = mapped_column(String(50), server_default="")
    # The KC the learner asked to practise (Q35a); NULL for a set planned freely.
    focus_kc_id: Mapped[str | None] = mapped_column(String(100))
    # Per KC of the set, its mastery when the learner began answering (Q35c):
    # {kc_id: {"p_mastery": float | null, "learned": bool}}; null before that.
    mastery_before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Why generation failed, as an error code; never model output.
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Exercise(Base):
    """One practice item, private to its learner (ADR 0021 §5).

    `content` and `answer` hold the format's models (`adaptive/exercise/formats.py`);
    `answer` is never sent before the learner has answered. Items the critic rejected
    are kept with status `rejected` so the critic can be evaluated (ADR 0021 §8).
    """

    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint(_in("format", FORMATS), name="format"),
        CheckConstraint(_in("status", EXERCISE_STATUSES), name="status"),
        Index("ix_exercises_set_id_position", "set_id", "position"),
        Index("ix_exercises_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exercise_sets.id", ondelete="CASCADE"))
    # Order within the set; rejected items share the slot of the item that replaced them.
    position: Mapped[int] = mapped_column(SmallInteger)
    # No FK: KC ids come from the checked-in catalog, as in kc_evidence.
    kc_id: Mapped[str] = mapped_column(String(100))
    format: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Prior difficulty from the rubric ratings (ADR 0012 §3), kept with the ratings so
    # the item can be re-priced when the rubric changes.
    difficulty: Mapped[float] = mapped_column(Float)
    ratings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # The critic's verdict, reasons and its own answer; NULL for bank items.
    critic: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10))
    # Set when the item came from the placement bank instead of the generator.
    bank_item_id: Mapped[str | None] = mapped_column(String(100))
    # "<connection>:<model>" that wrote it; NULL for bank items.
    model: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attempt(Base):
    """A learner's answer to one practice item and how it was graded (ADR 0021 §6)."""

    __tablename__ = "attempts"
    __table_args__ = (
        Index("ix_attempts_user_id_created_at", "user_id", "created_at"),
        Index("ix_attempts_exercise_id", "exercise_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"))
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    correct: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # Explanation shown, and the grader's other mistakes when a model graded it.
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
