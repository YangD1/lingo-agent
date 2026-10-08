"""/learner: the learner model page's data, and deleting it (P1 plan §7)."""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.kc.catalog import get_grammar_catalog
from app.db.models import PlacementSession, SkillEstimate, User, UserProfile
from app.memory.reflection import Reflection, TaggedMistake, UsedCorrectly
from tests.integration.test_activity_api import activity
from tests.integration.test_chat_send import connect, history, login, new_conversation, send
from tests.integration.test_learned_mastery import CATALOG, RULES, practice_set
from tests.integration.test_learned_mastery import KC as LEARNED_KC
from tests.integration.test_reflection import FakeReflector, idle, reflector  # noqa: F401

THIRD_PERSON = "g.present_simple_third_person"  # A1
ARTICLES = "g.articles_basic"  # A1
PAST = "g.past_simple_irregular"


def mistake(kc_id: str, original: str, severity: str = "medium") -> TaggedMistake:
    return TaggedMistake(
        message="u1",
        kc_id=kc_id,
        error_type="omission",
        severity=severity,  # type: ignore[arg-type]
        original=original,
        correction=f"{original} (fixed)",
    )


async def switch_to(client: AsyncClient, email: str) -> None:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


async def learner_model(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/learner")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def evidence(client: AsyncClient, kc_id: str) -> dict[str, Any]:
    response = await client.get(f"/learner/kcs/{kc_id}/evidence")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def chat_with_mistakes(
    client: AsyncClient, app: FastAPI, fake: FakeReflector, text: str = "She like a music."
) -> str:
    conversation_id = await new_conversation(client)
    fake.reflections.append(
        Reflection(
            mistakes=[
                mistake(THIRD_PERSON, "She like"),
                mistake(ARTICLES, "a music", severity="low"),
            ],
            used_correctly=[UsedCorrectly(message="u1", kc_id=PAST)],
        )
    )
    await send(client, conversation_id, text)
    await idle(app)
    return conversation_id


async def test_lists_the_grammar_points_met_weakest_first_with_their_evidence(
    client: AsyncClient,
    app: FastAPI,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    empty = await learner_model(client)
    assert empty["kcs"] == [] and empty["skills"] == []
    assert empty["thresholds"] == {"mastered": 0.95, "weak": 0.4}
    assert empty["gate"] == {"min_formats": 3, "min_span_hours": 20.0, "clean_days": 14}
    assert all(level["seen"] == 0 for level in empty["levels"].values())

    conversation_id = await chat_with_mistakes(client, app, reflector)
    body = await learner_model(client)

    kcs = {kc["kc_id"]: kc for kc in body["kcs"]}
    assert set(kcs) == {THIRD_PERSON, ARTICLES, PAST}
    assert body["kcs"][0]["kc_id"] == THIRD_PERSON  # the counted mistake: weakest
    assert body["kcs"][-1]["kc_id"] == PAST  # used correctly
    assert kcs[THIRD_PERSON] | {"p_mastery": None, "last_evidence_at": None} == {
        "kc_id": THIRD_PERSON,
        "name_en": kcs[THIRD_PERSON]["name_en"],
        "name_zh": kcs[THIRD_PERSON]["name_zh"],
        "cefr": "A1",
        "p_mastery": None,
        "state": "weak",
        "observations": 1,
        "recog_correct": 0,
        "produce_correct": 0,
        "mistakes": 1,
        "last_evidence_at": None,
        "formats_passed": [],
        "correct_span_hours": 0.0,
        "last_mistake_at": kcs[THIRD_PERSON]["last_mistake_at"],
        "mastered_at": None,
        "due": None,
        "prerequisites": kcs[THIRD_PERSON]["prerequisites"],
        "confusables": kcs[THIRD_PERSON]["confusables"],
    }
    assert kcs[THIRD_PERSON]["last_mistake_at"] is not None  # the conversation mistake
    # The grammar graph, with names: a prerequisite need not be listed itself (Q47e).
    catalog = get_grammar_catalog()
    for kc_id in kcs:
        kc = catalog.get(kc_id)
        assert kc is not None
        assert [r["kc_id"] for r in kcs[kc_id]["prerequisites"]] == list(kc.prerequisites)
        assert [r["kc_id"] for r in kcs[kc_id]["confusables"]] == list(catalog.confusables(kc_id))
    regular = catalog.get("g.past_simple_regular")
    assert regular is not None
    assert kcs[PAST]["prerequisites"] == [
        {
            "kc_id": regular.id,
            "name_en": regular.name_en,
            "name_zh": regular.name_zh,
            "cefr": regular.cefr,
        }
    ]
    # A low-severity slip is stored and shown, but BKT does not use it.
    assert kcs[ARTICLES]["observations"] == 0 and kcs[ARTICLES]["mistakes"] == 1
    assert kcs[PAST]["produce_correct"] == 1 and kcs[PAST]["mistakes"] == 0
    assert body["levels"]["A1"]["seen"] == 2 and body["levels"]["A1"]["total"] > 2

    page = await evidence(client, THIRD_PERSON)
    assert page["total"] == 1
    [item] = page["evidence"]
    assert item | {"id": None, "created_at": None} == {
        "id": None,
        "correct": False,
        "evidence": "production",
        "source": "chat",
        "error_type": "omission",
        "severity": "medium",
        "original": "She like",
        "correction": "She like (fixed)",
        "l1_transfer": False,
        "counted": True,
        "conversation_id": conversation_id,
        "conversation_title": "She like a music.",
        "created_at": None,
    }
    [slip] = (await evidence(client, ARTICLES))["evidence"]
    assert slip["counted"] is False

    # The conversation goes; the evidence stays, without its link.
    assert (await client.delete(f"/conversations/{conversation_id}")).status_code == 204
    [item] = (await evidence(client, THIRD_PERSON))["evidence"]
    assert item["conversation_id"] is None and item["conversation_title"] is None

    response = await client.get("/learner/kcs/g.no_such_point/evidence")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "kc_not_found"


async def test_deleting_one_piece_of_evidence_recomputes_and_untags_the_turn(
    client: AsyncClient,
    app: FastAPI,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await chat_with_mistakes(client, app, reflector)
    [item] = (await evidence(client, THIRD_PERSON))["evidence"]
    [correct] = (await evidence(client, PAST))["evidence"]

    # Someone else cannot.
    await login(client, "other@example.com")
    response = await client.delete(f"/learner/evidence/{item['id']}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "evidence_not_found"
    await switch_to(client, "learner@example.com")

    assert (await client.delete(f"/learner/evidence/{item['id']}")).status_code == 204
    assert (await client.delete(f"/learner/evidence/{correct['id']}")).status_code == 204

    kcs = [kc["kc_id"] for kc in (await learner_model(client))["kcs"]]
    assert kcs == [ARTICLES]  # the others have no evidence left
    [turn] = [m["id"] for m in await history(client, conversation_id) if m["role"] == "user"]
    [tags] = [
        a
        for a in (await activity(client, conversation_id, turn=turn))["activities"]
        if a["name"] == "grammar_tagging"
    ]
    assert [m["kc_id"] for m in tags["summary"]["mistakes"]] == [ARTICLES]
    assert tags["summary"]["used_correctly"] == []


async def test_deleting_everything_leaves_no_copy_and_spares_others(
    client: AsyncClient,
    app: FastAPI,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client, "other@example.com")
    await connect(client, "deepseek")
    await chat_with_mistakes(client, app, reflector)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await chat_with_mistakes(client, app, reflector)

    response = await client.delete("/learner")
    assert response.status_code == 200 and response.json() == {"deleted": 3}

    assert (await learner_model(client))["kcs"] == []
    assert (await evidence(client, THIRD_PERSON))["total"] == 0
    names = [a["name"] for a in (await activity(client, conversation_id))["activities"]]
    assert "grammar_tagging" not in names and "reflect_memory" in names
    await switch_to(client, "other@example.com")
    assert len((await learner_model(client))["kcs"]) == 3


async def test_skills_read_as_a_level_and_a_vocabulary_size(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Vocab's rating is ln V: the page gets the latest finished test's size instead."""
    await login(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    now = datetime.now(UTC)

    def placement(size: int, finished: datetime) -> PlacementSession:
        vocab = {"size": size, "half_known_rank": 4000, "reliable": True, "reference_cefr": "B1"}
        return PlacementSession(
            user_id=user.id,
            status="done",
            stage="grammar",
            seed=1,
            rules_version="x",
            result={"cefr": "B2", "vocab": vocab, "grammar": {}, "answers": {}},
            finished_at=finished,
        )

    db_session.add_all(
        [
            placement(1200, now - timedelta(days=90)),
            placement(3100, now),
            SkillEstimate(user_id=user.id, skill="grammar", rating=0.5, attempts=20),
            SkillEstimate(user_id=user.id, skill="vocab", rating=math.log(4000), attempts=40),
        ]
    )
    await db_session.commit()

    skills = {s["skill"]: s for s in (await learner_model(client))["skills"]}
    assert skills["grammar"]["cefr"] == "B2" and skills["grammar"]["vocab_size"] is None
    assert skills["vocab"] | {"rating": 0} == {
        "skill": "vocab",
        "rating": 0,
        "attempts": 40,
        "cefr": "B1",
        "vocab_size": 3100,
        "reliable": True,
    }


async def test_a_learned_grammar_point_shows_its_progress_and_review(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    user_id = await db_session.scalar(select(User.id).where(User.email == "learner@example.com"))
    assert user_id is not None
    db_session.add(UserProfile(user_id=user_id, cefr_level="B1"))
    await practice_set(db_session, user_id, [("choice4", 0, True), ("cloze", 0.1, True)])
    await practice_set(db_session, user_id, [("transform", 21, True)])
    await mastery.refresh(db_session, user_id, [LEARNED_KC], rules=RULES, catalog=CATALOG)
    await db_session.commit()

    [kc] = (await learner_model(client))["kcs"]
    assert kc["formats_passed"] == ["choice4", "cloze", "transform"]
    assert kc["correct_span_hours"] == 21.0
    assert kc["last_mistake_at"] is None
    assert kc["mastered_at"] is not None and kc["due"] is not None
