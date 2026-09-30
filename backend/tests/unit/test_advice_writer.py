"""The model picks among the candidates; code keeps it honest (P1 plan §7.5.2)."""

from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda

from app.adaptive.kc.catalog import get_grammar_catalog
from app.advice import writer
from app.advice.candidates import Candidate, Example
from app.advice.writer import AdviceDraft, DraftItem, Item, accept, fill, render_input
from app.db.models import UserProfile
from app.services.vocab.books import get_book

KC = get_grammar_catalog().get("g.present_simple_third_person")
assert KC is not None
CANDIDATES = [
    Candidate("placement", "placement", 1.0),
    Candidate("vocab_review", "vocab_review", 0.5, count=12),
    Candidate(
        f"grammar_practice:{KC.id}",
        "grammar_practice",
        0.4,
        count=3,
        kc=KC,
        p_mastery=0.23,
        examples=(Example('he "go" home', "he goes home"), Example("it work", None)),
    ),
    Candidate("vocab_learn", "vocab_learn", 0.3, count=5, book=get_book("cet4")),
]


def draft(*ids: str, title: str = "Do it", reason: str = "Because.") -> AdviceDraft:
    return AdviceDraft(items=[DraftItem(candidate_id=i, title=title, reason=reason) for i in ids])


def test_invented_and_repeated_ids_are_dropped() -> None:
    items = accept(
        draft("vocab_review", "grammar_practice:g.made_up", "/admin", "vocab_review", "placement"),
        CANDIDATES,
    )
    assert [i.candidate_id for i in items] == ["vocab_review", "placement"]


def test_at_most_three_and_text_is_cleaned() -> None:
    items = accept(
        draft(*(c.id for c in CANDIDATES), title="  Review\n now ", reason="x" * 1000), CANDIDATES
    )
    assert len(items) == writer.MAX_ITEMS
    assert items[0].title == "Review now"
    assert items[0].reason is not None and len(items[0].reason) == writer.MAX_REASON_CHARS
    assert items[0].reason.endswith("…")


def test_empty_text_is_dropped() -> None:
    assert accept(draft("placement", title="  "), CANDIDATES) == []


def test_templates_fill_up_to_three_best_first() -> None:
    items = fill([Item("vocab_learn", "Learn", "Why")], CANDIDATES)
    assert items == [Item("vocab_learn", "Learn", "Why"), Item("placement"), Item("vocab_review")]


def test_items_whose_candidate_is_gone_are_replaced() -> None:
    # The due words were reviewed: that advice no longer applies.
    cached = [Item("vocab_review", "Review", "Why"), Item("placement", "Test", "Why")]
    items = fill(cached, [c for c in CANDIDATES if c.id != "vocab_review"])
    assert [i.candidate_id for i in items] == [
        "placement",
        f"grammar_practice:{KC.id}",
        "vocab_learn",
    ]
    assert items[0].title == "Test" and items[1].title is None


def test_fewer_candidates_than_three() -> None:
    assert fill([], CANDIDATES[:1]) == [Item("placement")]
    assert fill([], []) == []


def test_input_has_the_candidates_their_evidence_and_the_profile() -> None:
    profile = UserProfile(goal="Pass IELTS in March", interests=["hiking"], daily_minutes=20)

    text = render_input(CANDIDATES, profile, "Simplified Chinese")

    assert text.startswith("Write in: Simplified Chinese")
    assert "- Goal: Pass IELTS in March" in text and "- Interests: hiking" in text
    assert "Level (CEFR)" not in text  # unknown fields are left out
    assert "- `placement`: Take the placement test: never taken" in text
    assert "- `vocab_review`: Review words that are due: 12 due" in text
    assert f"- `grammar_practice:{KC.id}`: " in text and "mastery 23%, 3 mistakes" in text
    # Learner text is quoted, with its own quotes neutralised.
    assert 'mistake: "he \'go\' home" -> "he goes home"' in text
    assert 'mistake: "it work"\n' in text
    assert "- `vocab_learn`: Learn today's new words from CET-4: 5 left today" in text
    assert "(nothing known yet)" in render_input(CANDIDATES, None, "English")


async def test_write_calls_the_advice_route(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, list[BaseMessage]]] = []

    def get_structured_llm(ctx: Any, task: str, schema: type) -> Runnable[Any, Any]:
        assert schema is AdviceDraft

        async def run(messages: list[BaseMessage], config: RunnableConfig | None = None) -> Any:
            seen.append((task, messages))
            return draft("vocab_review", "not_a_candidate")

        return RunnableLambda(run)

    monkeypatch.setattr(writer, "get_structured_llm", get_structured_llm)

    items = await writer.write(object(), CANDIDATES, None, language="English", config={})  # type: ignore[arg-type]

    assert items == [Item("vocab_review", "Do it", "Because.")]
    task, messages = seen[0]
    assert task == "advice" and "candidate_id" in str(messages[0].content)
