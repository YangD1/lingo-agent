"""The reflection evaluator (task 68.1): `reflection_input` -> the `reflect` task ->
the code that keeps what it may (`tagged_evidence`, `profile_changes`, `asked_words`),
as long-term memory is written after a turn (ADR 0009).

Each case is an exchange: the learner's profile and remembered facts, earlier messages
for context and the new ones to reflect on (learner messages get ids u1, u2, ...).
Metrics, each only on cases that set its expectation:

- `facts_found`: each expected fact is added or updated (one of its keywords appears).
- `nothing_forbidden`: no added or updated fact holds a forbidden keyword (one-off
  requests, small talk, health, other people's details, the learner's mistakes), and
  a case expecting no facts gets none.
- `outdated_fixed`: a fact the learner said is wrong or over is deleted or updated.
- `profile_right`: the stated profile fields are filled with these values.
- `mistakes_found`: each expected grammar mistake is kept, in its message, on one of
  the acceptable KCs, quoting the given words.
- `no_false_mistakes`: nothing is kept in a message whose English is correct.
- `words_found`: the words the learner asked about are kept, and no forbidden ones.
- `ids_valid`: every message, fact and KC id the model gave exists (before code
  drops the rest), so it did not make up ids.
- `no_unchanged` (no threshold): the model tagged no correct part as a mistake (a
  correction equal to the original; `tagged_evidence` drops those).
"""

import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from app.adaptive.kc.catalog import get_grammar_catalog
from app.db.models import UserProfile
from app.memory.reflection import (
    REFLECT_TASK,
    KnownFact,
    Reflection,
    asked_words,
    fact_ids,
    learner_message_ids,
    profile_changes,
    reflection_input,
    system_prompt,
    tagged_evidence,
)
from evals.dataset import Case
from evals.models import EvalModel
from evals.report import CaseResult


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    learner: str | None = None
    tutor: str | None = None


class ExpectedMistake(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str
    kcs: list[str] = Field(min_length=1)
    # Words of the wrong part; the kept `original` must contain them.
    words: str


class ReflectCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    language: str = "English"
    profile: dict[str, Any] = {}
    facts: list[str] = []
    earlier: list[Turn] = []
    new: list[Turn] = Field(min_length=1)
    # Each entry is one fact, as alternative keywords (any one will do).
    expect_facts: list[list[str]] = []
    expect_no_facts: bool = False
    forbid_facts: list[str] = []
    # Remembered facts (m1, m2, ...) that must be deleted or rewritten.
    expect_outdated: list[str] = []
    expect_profile: dict[str, Any] = {}
    expect_mistakes: list[ExpectedMistake] = []
    clean_messages: list[str] = []
    expect_words: list[str] = []
    forbid_words: list[str] = []


def _messages(turns: list[Turn], prefix: str) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for n, turn in enumerate(turns):
        if (turn.learner is None) == (turn.tutor is None):
            raise ValueError("a turn is either the learner's or the tutor's")
        if turn.learner is not None:
            out.append(HumanMessage(turn.learner, id=f"{prefix}{n}"))
        else:
            out.append(AIMessage(turn.tutor or "", id=f"{prefix}{n}t"))
    return out


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())


class ReflectEval:
    name = "reflect"

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        c = ReflectCase.model_validate(case.data)
        catalog = get_grammar_catalog()
        for m in c.expect_mistakes:
            if unknown := [k for k in m.kcs if k not in catalog]:
                raise ValueError(f"{case.id}: unknown KC {unknown}")
        known = [KnownFact(uuid.UUID(int=n + 1), text) for n, text in enumerate(c.facts)]
        new = _messages(c.new, "new")
        learner_ids = learner_message_ids(new)
        prompt = reflection_input(
            profile=UserProfile(**c.profile) if c.profile else None,
            facts=known,
            earlier=_messages(c.earlier, "old"),
            new=new,
            language=c.language,
        )
        out = await model.structured(
            case.id,
            REFLECT_TASK,
            Reflection,
            [SystemMessage(system_prompt()), HumanMessage(prompt)],
        )
        checks: dict[str, bool] = {}
        written = [
            _fold(op.content or "") for op in out.memory_ops if op.action in ("add", "update")
        ]
        if c.expect_facts:
            checks["facts_found"] = all(
                any(_fold(k) in w for k in alternatives for w in written)
                for alternatives in c.expect_facts
            )
        if c.forbid_facts or c.expect_no_facts:
            checks["nothing_forbidden"] = not (c.expect_no_facts and written) and not any(
                _fold(k) in w for k in c.forbid_facts for w in written
            )
        if c.expect_outdated:
            touched = {op.id for op in out.memory_ops if op.action in ("delete", "update")}
            checks["outdated_fixed"] = set(c.expect_outdated) <= touched
        if c.expect_profile:
            changes = profile_changes(out.profile_updates)
            checks["profile_right"] = all(
                _same(changes.get(k), v) for k, v in c.expect_profile.items()
            )
        texts = {m.id: m.text for m in new if isinstance(m, HumanMessage) and m.id}
        kept = tagged_evidence(out, learner_ids, catalog, texts)
        short = {v: k for k, v in learner_ids.items()}
        wrong = [(short[e.message_id], e) for e in kept if not e.correct]
        if c.expect_mistakes:
            checks["mistakes_found"] = all(
                any(
                    sid == m.message
                    and e.kc_id in m.kcs
                    and _fold(m.words) in _fold(e.original or "")
                    for sid, e in wrong
                )
                for m in c.expect_mistakes
            )
        if c.clean_messages:
            checks["no_false_mistakes"] = not any(sid in c.clean_messages for sid, _ in wrong)
        if c.expect_words or c.forbid_words:
            words = {w.casefold() for _, w in asked_words(out, learner_ids)}
            checks["words_found"] = {w.casefold() for w in c.expect_words} <= words and not (
                {w.casefold() for w in c.forbid_words} & words
            )
        facts = fact_ids(known)
        checks["ids_valid"] = (
            all(m.message in learner_ids and m.kc_id in catalog for m in out.mistakes)
            and all(u.message in learner_ids and u.kc_id in catalog for u in out.used_correctly)
            and all(op.id in facts for op in out.memory_ops if op.action in ("update", "delete"))
        )
        checks["no_unchanged"] = not any(
            _fold(m.original) == _fold(m.correction) for m in out.mistakes
        )
        detail = "\n".join(
            [f"fact {op.action} {op.id or ''}: {op.content or ''}" for op in out.memory_ops]
            + [
                f"profile: {changes}"
                for changes in [profile_changes(out.profile_updates)]
                if changes
            ]
            + [
                f"mistake {m.message} {m.kc_id}: {m.original} -> {m.correction}"
                for m in out.mistakes
            ]
            + [f"word {v.message}: {v.word}" for v in out.vocab_candidates]
        )
        return CaseResult(case.id, checks, detail)


def _same(got: object, want: object) -> bool:
    if isinstance(want, str) and isinstance(got, str):
        return _fold(want) in _fold(got)
    if isinstance(want, list) and isinstance(got, list):
        return {_fold(str(w)) for w in want} <= {_fold(str(g)) for g in got}
    return got == want
