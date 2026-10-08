"""/learner/diagnosis: the tutor's diagnosis on the learner model page (task 47)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.diagnosis.boost import load_boost
from app.adaptive.rules import get_rules
from app.db.models import Conversation, Diagnosis, KCEvidence, Memory
from app.memory.service import add_memory
from tests.integration.test_word_examples_prefetch import learner

THIRD_PERSON = "g.present_simple_third_person"
BE = "g.be_present"
RULES = get_rules()


def _mistake(user_id: uuid.UUID, kc_id: str, n: int, **fields: Any) -> KCEvidence:
    return KCEvidence(
        user_id=user_id,
        kc_id=kc_id,
        correct=False,
        evidence="production",
        source="chat",
        error_type="wrong_form",
        severity="medium",
        original=f"wrong {n}",
        correction=f"right {n}",
        **fields,
    )


def _diagnosis(
    user_id: uuid.UUID,
    causes: list[dict[str, Any]],
    *,
    days_ago: float = 1,
    memory_id: uuid.UUID | None = None,
) -> Diagnosis:
    return Diagnosis(
        user_id=user_id,
        trigger="weekly",
        target_kc_ids=[THIRD_PERSON],
        root_causes=causes,
        language="zh",
        evidence_upto=None,
        model="conn:model",
        rules_version=RULES.version,
        memory_id=memory_id,
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def _cause(kc_ids: list[str], evidence_ids: list[int], text: str = "Cause.") -> dict[str, Any]:
    return {
        "hypothesis": text,
        "kc_ids": kc_ids,
        "evidence_ids": evidence_ids,
        "confidence": "medium",
        "suggestion": "Practise it.",
    }


async def _page(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/learner/diagnosis")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_nothing_before_the_first_diagnosis(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await learner(client, db_session, model=False)
    assert await _page(client) == {"enabled": True, "diagnosis": None, "checked_at": None}

    response = await client.put("/me/background/diagnosis", json={"enabled": False})
    assert response.status_code == 200, response.text
    assert (await _page(client))["enabled"] is False


async def test_the_latest_diagnosis_with_causes_and_its_cited_mistakes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, tenant_id = await learner(client, db_session, model=False)
    conversation = Conversation(tenant_id=tenant_id, user_id=user_id, title="Weekend")
    db_session.add(conversation)
    await db_session.flush()
    rows = [
        _mistake(user_id, THIRD_PERSON, 0, conversation_id=conversation.id),
        _mistake(user_id, THIRD_PERSON, 1),
        _mistake(user_id, BE, 2),
    ]
    db_session.add_all(rows)
    await db_session.flush()
    ids = [r.id for r in rows]
    db_session.add_all(
        [
            _diagnosis(user_id, [_cause([THIRD_PERSON], ids[:2], "Old.")], days_ago=20),
            _diagnosis(
                user_id,
                [_cause([BE, THIRD_PERSON, "g.gone"], [ids[2], ids[0], 999_999], "Root in be.")],
                days_ago=3,
            ),
            # Looked again later and found nothing: shown as a later check (Q47a).
            _diagnosis(user_id, [], days_ago=1),
        ]
    )
    await db_session.commit()

    body = await _page(client)
    d = body["diagnosis"]
    assert d["boost_active"] is True
    assert body["checked_at"] > d["created_at"]
    [cause] = d["root_causes"]
    assert cause["hypothesis"] == "Root in be."
    # KCs gone from the catalog are left out; root first.
    assert [k["kc_id"] for k in cause["kcs"]] == [BE, THIRD_PERSON]
    assert cause["kcs"][0]["name_zh"]
    assert cause["kcs"][0]["learned"] is False
    # Cited order; the missing one is only counted (Q47d).
    assert [e["id"] for e in cause["evidence"]] == [ids[2], ids[0]]
    assert cause["cited"] == 3
    assert cause["evidence"][1]["conversation_title"] == "Weekend"
    assert cause["evidence"][1]["original"] == "wrong 0"
    assert cause["evidence"][0]["kc_id"] == BE


async def test_an_old_diagnosis_no_longer_boosts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, _ = await learner(client, db_session, model=False)
    db_session.add(_diagnosis(user_id, [_cause([BE], [])], days_ago=RULES.diagnosis.boost_days + 1))
    await db_session.commit()

    d = (await _page(client))["diagnosis"]
    assert d["boost_active"] is False
    assert d["root_causes"][0]["evidence"] == []


async def test_another_learners_diagnosis_is_not_shown(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    other, _ = await learner(client, db_session, model=False)
    db_session.add(_diagnosis(other, [_cause([BE], [])]))
    await db_session.commit()
    await learner(client, db_session, model=False)
    assert (await _page(client))["diagnosis"] is None


async def test_deleting_all_learning_records_deletes_diagnoses_and_their_memory(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, tenant_id = await learner(client, db_session, model=False)
    memory = await add_memory(
        db_session, tenant_id=tenant_id, user_id=user_id, kind="fact", content="Diagnosis: x"
    )
    other = await add_memory(
        db_session, tenant_id=tenant_id, user_id=user_id, kind="fact", content="Likes tea."
    )
    memory_id, other_id = memory.id, other.id
    db_session.add(_diagnosis(user_id, [_cause([BE], [])], memory_id=memory_id))
    await db_session.commit()

    response = await client.delete("/learner")
    assert response.status_code == 200, response.text
    db_session.expire_all()
    count = select(func.count()).select_from(Diagnosis).where(Diagnosis.user_id == user_id)
    assert await db_session.scalar(count) == 0
    assert await db_session.scalar(select(Memory.id).where(Memory.id == memory_id)) is None
    assert await db_session.scalar(select(Memory.id).where(Memory.id == other_id)) == other_id


async def test_deleting_a_diagnosis_ends_its_boost_and_deletes_its_memory(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, tenant_id = await learner(client, db_session, model=False)
    memory = await add_memory(
        db_session, tenant_id=tenant_id, user_id=user_id, kind="fact", content="Diagnosis: x"
    )
    memory_id = memory.id
    old = _diagnosis(user_id, [_cause([THIRD_PERSON], [], "Old.")], days_ago=3, memory_id=memory_id)
    new = _diagnosis(user_id, [_cause([BE], [], "New.")], days_ago=1, memory_id=memory_id)
    db_session.add_all([old, new])
    await db_session.flush()
    old_id, new_id = old.id, new.id
    await db_session.commit()

    # An older one: the memory now says what the newer one found, so it stays.
    response = await client.delete(f"/learner/diagnoses/{old_id}")
    assert response.status_code == 204, response.text
    db_session.expire_all()
    assert await db_session.scalar(select(Memory.id).where(Memory.id == memory_id)) == memory_id

    response = await client.delete(f"/learner/diagnoses/{new_id}")
    assert response.status_code == 204, response.text
    db_session.expire_all()
    assert await db_session.scalar(select(Memory.id).where(Memory.id == memory_id)) is None
    assert (await _page(client))["diagnosis"] is None
    boost = await load_boost(db_session, user_id, learned=(), rules=RULES, now=datetime.now(UTC))
    assert boost == {}

    response = await client.delete(f"/learner/diagnoses/{new_id}")
    assert response.status_code == 404


async def test_another_learners_diagnosis_cannot_be_deleted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    other, _ = await learner(client, db_session, model=False)
    row = _diagnosis(other, [_cause([BE], [])])
    db_session.add(row)
    await db_session.flush()
    row_id = row.id
    await db_session.commit()
    await learner(client, db_session, model=False)

    response = await client.delete(f"/learner/diagnoses/{row_id}")
    assert response.status_code == 404
    db_session.expire_all()
    assert await db_session.scalar(select(Diagnosis.id).where(Diagnosis.id == row_id)) == row_id
