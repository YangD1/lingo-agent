import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.adaptive.rules import get_rules
from app.agents.exercise_graph import ModelReply
from app.agents.reading_graph import (
    ReadingContext,
    RewriteResult,
    Stage,
    build_reading_graph,
    start_state,
)
from app.providers.errors import NoModelConfiguredError
from app.services.reading.messages import source_paragraphs

RULES = get_rules()
GRAPH = build_reading_graph()


def text(words: int) -> list[str]:
    """Paragraphs of 10-word sentences: "Fact 1 is that the comet has blue light today."""
    sentences = [f"Fact {i} is that the comet has blue light today." for i in range(words // 10)]
    return [" ".join(sentences[i : i + 5]) for i in range(0, len(sentences), 5)]


def question(position: int, *, evidence: str | None = None) -> dict[str, Any]:
    return {
        "position": position,
        "question": f"What is fact {position} about?",
        "correct": f"The comet {position}",
        "distractors": [f"A dog {position}", f"A ship {position}", f"A tree {position}"],
        "evidence": evidence or f"Fact {position} is that the comet has blue light today.",
    }


def section(messages: Sequence[BaseMessage], title: str) -> Any:
    content = messages[-1].content
    assert isinstance(content, str)
    start = content.index(title) + len(title)
    end = content.find("\n\n", start)
    return json.loads(content[start : end if end != -1 else None])


@dataclass
class FakeModels:
    """The writer writes `words` words and a valid question per position; the critic
    picks the right option, except for (review call, position) in `bad`."""

    words: list[int] = field(default_factory=lambda: [300])
    broken: set[int] = field(default_factory=set)
    bad: set[tuple[int, int]] = field(default_factory=set)
    rewrite_error: Exception | None = None
    critic_error: Exception | None = None
    rewrites: list[str] = field(default_factory=list)
    asked: list[list[int]] = field(default_factory=list)
    reviewed: list[list[int]] = field(default_factory=list)

    async def rewrite(self, messages: Sequence[BaseMessage], schema: type[BaseModel]) -> ModelReply:
        if self.rewrite_error is not None:
            raise self.rewrite_error
        self.rewrites.append(str(messages[-1].content))
        words = self.words[min(len(self.rewrites), len(self.words)) - 1]
        questions = [
            question(p, evidence="Not in the text." if p in self.broken else None)
            for p in range(1, RULES.reading.questions + 1)
        ]
        data = {"title": "Comet news", "paragraphs": text(words), "questions": questions}
        return ModelReply(schema.model_validate(data), "fake:writer")

    async def questions(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        asked = [r["position"] for r in section(messages, "write a new one for each position:\n")]
        self.asked.append(asked)
        data = {"questions": [question(p) for p in asked]}
        return ModelReply(schema.model_validate(data), "fake:writer")

    async def critique(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        if self.critic_error is not None:
            raise self.critic_error
        shown = section(messages, "Questions to review:\n")
        call = len(self.reviewed)
        self.reviewed.append([q["position"] for q in shown])
        reviews = []
        for q in shown:
            p = q["position"]
            bad = (call, p) in self.bad
            reviews.append(
                {
                    "position": p,
                    "own_answer": q["options"].index(f"The comet {p}"),
                    "answer_in_text": True,
                    "one_answer": not bad,
                    "needs_text": True,
                    "content_ok": True,
                    "problems": ["Two options fit."] if bad else [],
                }
            )
        return ModelReply(schema.model_validate({"reviews": reviews}), "fake:critic")


async def run(models: FakeModels) -> tuple[RewriteResult, list[Stage]]:
    saved: list[RewriteResult] = []
    stages: list[Stage] = []

    async def save(result: RewriteResult) -> None:
        saved.append(result)

    async def report(stage: Stage) -> None:
        stages.append(stage)

    ctx = ReadingContext(
        rewrite=models.rewrite,
        questions=models.questions,
        critique=models.critique,
        title="A comet seen",
        source=["Original paragraph one.", "Original paragraph two."],
        level="A2",
        rules=RULES,
        seed=7,
        save=save,
        report=report,
    )
    await GRAPH.ainvoke(start_state(RULES), context=ctx)
    assert len(saved) == 1
    return saved[0], stages


async def test_all_questions_pass() -> None:
    models = FakeModels()
    result, stages = await run(models)
    assert result.error_code is None
    assert result.title == "Comet news"
    assert len(result.paragraphs) == 6
    assert [q.position for q in result.questions] == [1, 2, 3, 4, 5]
    first = result.questions[0]
    assert first.options[first.answer] == "The comet 1"
    assert result.rejected == []
    assert (result.model, result.critic_model) == ("fake:writer", "fake:critic")
    assert stages == ["rewriting", "reviewing"]
    assert "Learner's level (CEFR): A2" in models.rewrites[0]
    assert "Length of the rewrite: 250 to 400 words" in models.rewrites[0]


async def test_options_are_shuffled() -> None:
    result, _ = await run(FakeModels())
    assert len({q.answer for q in result.questions}) > 1


async def test_rejected_questions_are_rewritten_once_then_dropped() -> None:
    # Call 0 rejects 2 and 4; the rewrite of 2 passes in call 1, 4 fails again.
    models = FakeModels(bad={(0, 2), (0, 4), (1, 4)})
    result, stages = await run(models)
    assert models.asked == [[2, 4]]
    assert models.reviewed == [[1, 2, 3, 4, 5], [2, 4]]
    assert [q.position for q in result.questions] == [1, 2, 3, 5]
    assert len(result.rejected) == 3
    assert "more than one option could be right" in result.rejected[0]["reasons"]
    assert result.rejected[0]["review"]["problems"] == ["Two options fit."]
    assert stages == ["rewriting", "reviewing", "fixing", "reviewing"]


async def test_question_with_invented_evidence_goes_straight_to_rewriting() -> None:
    models = FakeModels(broken={3})
    result, _ = await run(models)
    assert models.reviewed[0] == [1, 2, 4, 5]
    assert models.asked == [[3]]
    assert [q.position for q in result.questions] == [1, 2, 3, 4, 5]


async def test_text_of_the_wrong_length_is_written_again() -> None:
    models = FakeModels(words=[100, 300])
    result, _ = await run(models)
    assert result.error_code is None
    assert len(models.rewrites) == 2
    assert "the rewrite has 100 words" in models.rewrites[1]


async def test_text_wrong_twice_fails() -> None:
    models = FakeModels(words=[100, 900])
    result, _ = await run(models)
    assert result.error_code == "rewrite_invalid"
    assert result.paragraphs == []
    assert models.reviewed == []


async def test_model_errors() -> None:
    result, _ = await run(FakeModels(rewrite_error=RuntimeError("down")))
    assert result.error_code == "generation_failed"

    missing = NoModelConfiguredError("llm", "article_rewrite", [])
    result, _ = await run(FakeModels(rewrite_error=missing))
    assert result.error_code == missing.code


async def test_critic_failure_keeps_the_text_without_questions() -> None:
    result, _ = await run(FakeModels(critic_error=RuntimeError("down")))
    assert result.error_code is None
    assert result.paragraphs
    assert result.questions == []


def test_source_paragraphs_cut_at_a_boundary() -> None:
    body = "one two three\n\nfour five\n\n\n\nsix seven eight nine"
    assert source_paragraphs(body, 5) == ["one two three", "four five"]
    assert source_paragraphs(body, 2) == ["one two three"]
