"""Example sentences for the word popup, written by a model on request (ADR 0017 §3).

Cached per tenant, word and level: a cached word costs nothing. Every sentence is
checked in code to use the word or one of its forms; sentences that don't are dropped.
"""

import re
import uuid
from collections.abc import Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Word, WordExample
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm

TASK = "word_examples"
SENTENCES = 2
# A level for learners not assessed yet: easy sentences suit them best.
DEFAULT_LEVEL = "A2"

_TOKEN = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")


class Example(BaseModel):
    en: str = Field(description="The English sentence")
    zh: str = Field(description="Its Simplified Chinese translation")


class WordExamples(BaseModel):
    sentences: list[Example] = Field(description=f"{SENTENCES} example sentences")


class ExamplesInvalidError(Exception):
    """The model wrote no sentence that uses the word."""


def word_forms(word: Word) -> set[str]:
    """The word and its inflections from ECDICT's `exchange` ("p:went/d:gone/0:go"),
    lowercase. `1:` lists inflection kinds, not words."""
    forms = {word.word.lower()}
    for part in (word.exchange or "").split("/"):
        kind, _, form = part.partition(":")
        if form and kind != "1":
            forms.add(form.lower())
    return forms


def uses_word(sentence: str, forms: set[str]) -> bool:
    lowered = sentence.lower()
    tokens = {t.replace("\u2019", "'") for t in _TOKEN.findall(lowered)}
    # Phrases ("look up") are matched as text; single words as whole words.
    return any(f in lowered if " " in f else f in tokens for f in forms)


def keep_valid(word: Word, sentences: Sequence[Example]) -> list[dict[str, str]]:
    forms = word_forms(word)
    return [
        {"en": s.en.strip(), "zh": s.zh.strip()}
        for s in sentences[:SENTENCES]
        if s.en.strip() and uses_word(s.en, forms)
    ]


async def cached(
    session: AsyncSession, tenant_id: uuid.UUID, word_id: int, cefr: str
) -> list[dict[str, str]] | None:
    return await session.scalar(
        select(WordExample.sentences).where(
            WordExample.tenant_id == tenant_id,
            WordExample.word_id == word_id,
            WordExample.cefr == cefr,
        )
    )


async def examples(
    session: AsyncSession,
    ctx: TenantProviderContext,
    word: Word,
    cefr: str,
    config: RunnableConfig,
) -> list[dict[str, str]]:
    """Cached sentences, or new ones from the model (raises NoModelConfiguredError,
    ExamplesInvalidError, or the provider's error)."""
    found = await cached(session, ctx.tenant_id, word.id, cefr)
    if found is not None:
        return found
    llm = get_structured_llm(ctx, TASK, WordExamples)
    prompt = (
        f"Word: {word.word}\nChinese glosses:\n{word.translation}\n"
        f"Learner's level (CEFR): {cefr}\nSentences: {SENTENCES}"
    )
    result = await llm.ainvoke(
        [SystemMessage(load_prompt(TASK)), HumanMessage(prompt)], config=config
    )
    sentences = keep_valid(word, result.sentences)
    if not sentences:
        raise ExamplesInvalidError
    # Two learners asking at once: the first one's sentences stay.
    await session.execute(
        insert(WordExample)
        .values(tenant_id=ctx.tenant_id, word_id=word.id, cefr=cefr, sentences=sentences)
        .on_conflict_do_nothing()
    )
    await session.commit()
    return await cached(session, ctx.tenant_id, word.id, cefr) or sentences
