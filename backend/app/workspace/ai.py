"""The reading view's model calls (ADR 0043 §4): a paragraph's translation and a
sentence's analysis, made when the learner asks and kept with the document.

Kept by a hash of the text, so the same paragraph or sentence calls no model again,
even after edits elsewhere; the analysis is an explanation, not evidence, so nothing
here touches mastery.
"""

import asyncio
import hashlib
import uuid
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile, WorkspaceAnnotation, WorkspaceDoc
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm
from app.workspace import service

TRANSLATE_TASK = "translate"
ANALYSIS_TASK = "sentence_analysis"
# Paragraphs translated in one request: those scrolled into view.
MAX_PARAGRAPHS_PER_REQUEST = 6
MAX_SENTENCE_CHARS = 1000

type ExplainIn = Literal["zh", "en"]
_LANGUAGES: dict[ExplainIn, str] = {"zh": "Simplified Chinese", "en": "English"}


class ParagraphNotFoundError(service.WorkspaceError):
    code = "workspace_paragraph_not_found"


class SentenceNotFoundError(service.WorkspaceError):
    code = "workspace_sentence_not_found"


class NotReadingError(service.WorkspaceError):
    code = "workspace_not_reading"


class AnalysisInvalidError(Exception):
    """The model's analysis did not fit the sentence."""


class Translation(BaseModel):
    text: str = Field(description="The paragraph in Simplified Chinese")


class Clause(BaseModel):
    text: str = Field(description="The clause or phrase, copied exactly from the sentence")
    role: str = Field(description="What kind it is and what it does in the sentence")


class Phrase(BaseModel):
    text: str = Field(description="The expression, copied exactly from the sentence")
    meaning: str = Field(description="What it means here")


class SentenceAnalysis(BaseModel):
    main: str = Field(description="The sentence's core: subject + verb (+ object/complement)")
    clauses: list[Clause] = Field(default_factory=list)
    phrases: list[Phrase] = Field(default_factory=list)
    meaning: str = Field(description="The whole sentence in Simplified Chinese")
    tip: str = Field(default="", description="The hardest point, in one short sentence")


def _key(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _flat(text: str) -> str:
    return " ".join(text.split())


async def _cached(
    session: AsyncSession, doc_id: uuid.UUID, kind: str, keys: list[str]
) -> dict[str, dict[str, object]]:
    rows = await session.execute(
        select(WorkspaceAnnotation.key, WorkspaceAnnotation.content).where(
            WorkspaceAnnotation.doc_id == doc_id,
            WorkspaceAnnotation.kind == kind,
            WorkspaceAnnotation.key.in_(keys),
        )
    )
    return {key: content for key, content in rows.tuples()}


async def _keep(
    session: AsyncSession, doc_id: uuid.UUID, kind: str, key: str, content: dict[str, object]
) -> None:
    await session.execute(
        insert(WorkspaceAnnotation)
        .values(doc_id=doc_id, kind=kind, key=key, content=content)
        .on_conflict_do_nothing()
    )


async def _paragraphs(session: AsyncSession, doc: WorkspaceDoc) -> list[str]:
    if doc.kind != "reading":
        raise NotReadingError("only a reading document has paragraphs")
    current = await service.get_version(session, doc)
    return list(current.content["paragraphs"])


async def translate(
    session: AsyncSession,
    ctx: TenantProviderContext,
    doc: WorkspaceDoc,
    indexes: list[int],
    config: RunnableConfig,
) -> dict[int, str]:
    """The current version's paragraphs at `indexes`, in Chinese: from the cache, or
    one call per paragraph, made together (raises NoModelConfiguredError or the
    provider's error)."""
    paragraphs = await _paragraphs(session, doc)
    if any(not 0 <= i < len(paragraphs) for i in indexes):
        raise ParagraphNotFoundError("no such paragraph")
    keys = {i: _key("zh", paragraphs[i]) for i in dict.fromkeys(indexes)}
    found = await _cached(session, doc.id, "translation", list(keys.values()))
    missing = [i for i, key in keys.items() if key not in found]
    if missing:
        llm = get_structured_llm(ctx, TRANSLATE_TASK, Translation)
        system = SystemMessage(load_prompt("workspace_translate"))
        results = await asyncio.gather(
            *(
                llm.ainvoke([system, HumanMessage(f"## Paragraph\n{paragraphs[i]}")], config=config)
                for i in missing
            )
        )
        for i, result in zip(missing, results, strict=True):
            content: dict[str, object] = {"text": result.text.strip()}
            await _keep(session, doc.id, "translation", keys[i], content)
            found[keys[i]] = content
        await session.commit()
    return {i: str(found[key]["text"]) for i, key in keys.items()}


def _check_analysis(sentence: str, result: SentenceAnalysis) -> dict[str, object]:
    """Clauses and phrases the sentence really has; the rest are dropped."""
    lowered = _flat(sentence).lower()

    def present(text: str) -> bool:
        text = _flat(text).strip(" .,;:")
        return bool(text) and text.lower() in lowered

    if not result.meaning.strip() or not result.main.strip():
        raise AnalysisInvalidError
    return {
        "main": result.main.strip(),
        "clauses": [c.model_dump() for c in result.clauses if present(c.text)][:8],
        "phrases": [p.model_dump() for p in result.phrases if present(p.text)][:5],
        "meaning": result.meaning.strip(),
        "tip": result.tip.strip(),
    }


async def explain_in(session: AsyncSession, user_id: uuid.UUID) -> ExplainIn:
    language = await session.scalar(
        select(UserProfile.explanation_language).where(UserProfile.user_id == user_id)
    )
    return "en" if language == "en" else "zh"


async def analyze(
    session: AsyncSession,
    ctx: TenantProviderContext,
    doc: WorkspaceDoc,
    paragraph: int,
    sentence: str,
    config: RunnableConfig,
) -> dict[str, object]:
    """How `sentence`, in the current version's paragraph, is built (raises
    AnalysisInvalidError, NoModelConfiguredError, or the provider's error)."""
    paragraphs = await _paragraphs(session, doc)
    if not 0 <= paragraph < len(paragraphs):
        raise ParagraphNotFoundError("no such paragraph")
    sentence = _flat(sentence)
    # Only text from the document: the endpoint is not a free analysis service.
    if len(sentence) < 2 or sentence not in _flat(paragraphs[paragraph]):
        raise SentenceNotFoundError("the sentence is not in that paragraph")
    language = await explain_in(session, doc.user_id)
    key = _key(language, sentence)
    found = await _cached(session, doc.id, "analysis", [key])
    if key in found:
        return found[key]
    llm = get_structured_llm(ctx, ANALYSIS_TASK, SentenceAnalysis)
    prompt = (
        f"Explanation language: {_LANGUAGES[language]}\n\n"
        f"## Paragraph\n{paragraphs[paragraph]}\n\n## Sentence\n{sentence}"
    )
    result = await llm.ainvoke(
        [SystemMessage(load_prompt("sentence_analysis")), HumanMessage(prompt)], config=config
    )
    content = _check_analysis(sentence, result)
    await _keep(session, doc.id, "analysis", key, content)
    await session.commit()
    return content
