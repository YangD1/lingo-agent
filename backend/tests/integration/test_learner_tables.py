import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, KCEvidence, KCMastery, SkillEstimate, Tenant, User


async def _user(session: AsyncSession) -> tuple[User, Tenant]:
    tenant = Tenant(name="personal", kind="personal")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    return user, tenant


def mistake(user: User, **kw: object) -> KCEvidence:
    fields: dict[str, object] = {
        "user_id": user.id,
        "kc_id": "g.present_simple_third_person",
        "correct": False,
        "evidence": "production",
        "source": "chat",
        "message_id": "m1",
        "error_type": "omission",
        "severity": "medium",
        "original": "She like music",
        "correction": "She likes music",
    }
    return KCEvidence(**(fields | kw))


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"error_type": None}, "ck_kc_evidence_mistake_fields"),
        ({"severity": None}, "ck_kc_evidence_mistake_fields"),
        ({"correct": True}, "ck_kc_evidence_mistake_fields"),  # success with error fields
        ({"error_type": "typo"}, "ck_kc_evidence_error_type"),
        ({"severity": "fatal"}, "ck_kc_evidence_severity"),
        ({"evidence": "vibes"}, "ck_kc_evidence_evidence"),
        ({"source": "email"}, "ck_kc_evidence_source"),
    ],
)
async def test_evidence_checks(
    db_session: AsyncSession, override: dict[str, object], constraint: str
) -> None:
    user, _ = await _user(db_session)
    db_session.add(mistake(user, **override))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_success_row_without_error_fields(db_session: AsyncSession) -> None:
    user, _ = await _user(db_session)
    db_session.add(
        mistake(user, correct=True, error_type=None, severity=None, original=None, correction=None)
    )
    await db_session.flush()


async def test_evidence_outlives_conversation_and_dies_with_user(db_session: AsyncSession) -> None:
    user, tenant = await _user(db_session)
    conversation = Conversation(tenant_id=tenant.id, user_id=user.id)
    db_session.add(conversation)
    await db_session.flush()
    db_session.add_all(
        [
            mistake(user, conversation_id=conversation.id),
            KCMastery(
                user_id=user.id,
                kc_id="g.present_simple_third_person",
                kind="grammar",
                p_mastery=0.3,
                rules_version="v",
            ),
            SkillEstimate(user_id=user.id, skill="grammar", rating=0.4, attempts=3),
        ]
    )
    await db_session.commit()

    await db_session.delete(conversation)
    await db_session.commit()
    db_session.expunge_all()
    evidence = await db_session.scalar(select(KCEvidence))
    assert evidence is not None and evidence.conversation_id is None

    await db_session.delete(await db_session.get(User, user.id))
    await db_session.commit()
    for model in (KCEvidence, KCMastery, SkillEstimate):
        assert await db_session.scalar(select(model)) is None


async def test_mastery_and_skill_checks(db_session: AsyncSession) -> None:
    user, _ = await _user(db_session)
    user_id = user.id
    await db_session.commit()  # keep the user across the rollback below
    db_session.add(
        KCMastery(user_id=user_id, kc_id="g.x", kind="grammar", p_mastery=1.2, rules_version="v")
    )
    with pytest.raises(IntegrityError, match="ck_kc_mastery_p_mastery"):
        await db_session.flush()
    await db_session.rollback()
    db_session.add(SkillEstimate(user_id=user_id, skill="juggling", rating=0.0))
    with pytest.raises(IntegrityError, match="ck_skill_estimates_skill"):
        await db_session.flush()
