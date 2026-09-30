"""What the tutor is told in a study-planning or daily conversation (ADR 0015 §6, 0016).

A planning conversation starts from the placement result page, a daily one from the
dashboard. Each turn the tutor gets the latest placement result, the grammar points the
test found weak, and the advice candidates (`advice/candidates.py`); the two differ only
in how they are told to use them. The algorithm still decides what can be
done: the practice and link cards the tutor may show are limited to these (the card
scope); proposals to change the word book or goal are for the learner to confirm.

Like the practice guidance, it goes into that call's system prompt only and is
rebuilt every turn, so the numbers are current.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive import mastery
from app.adaptive.kc.catalog import GrammarKC, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice.candidates import Candidate, Kind, candidates
from app.advice.describe import describe
from app.cards.tools import CardScope, LinkKind
from app.db.models import KCEvidence, KCMastery, PlacementSession
from app.prompts import load_prompt
from app.services.vocab.scheduler import learner_zone

# Which conversation the brief is for: the prompt around it differs.
type PlanningPurpose = Literal["planning", "daily"]

# Grammar points the latest test found weak, weakest first.
MISSED_SHOWN = 5

# The page each advice candidate leads to, as a link card.
_LINKS: dict[Kind, LinkKind] = {
    "vocab_review": "vocab_review",
    "vocab_learn": "vocab_review",
    "vocab_screen": "vocab_screen",
    "placement": "placement",
    "choose_book": "word_books",
}


@dataclass(frozen=True)
class MissedKC:
    kc: GrammarKC
    p_mastery: float


@dataclass(frozen=True)
class PlanningBrief:
    # The latest finished placement test's result (api/placement.py ResultOut); None if
    # the learner has none.
    placement: dict[str, Any] | None = None
    # Grammar points answered wrong in that test and not mastered since.
    missed: Sequence[MissedKC] = ()
    candidates: Sequence[Candidate] = field(default_factory=list)
    purpose: PlanningPurpose = "planning"

    def scope(self) -> CardScope:
        """The practice and link cards the tutor may show."""
        kc_ids = {m.kc.id for m in self.missed}
        kc_ids |= {c.kc.id for c in self.candidates if c.kc is not None}
        links: set[LinkKind] = {_LINKS[c.kind] for c in self.candidates if c.kind in _LINKS}
        links.add("learner")  # the placement result's skill estimates are shown there
        return CardScope(kc_ids=kc_ids, links=links)


class PlanningSource(Protocol):
    async def load(self) -> PlanningBrief: ...


class DatabasePlanning:
    """PlanningSource for one learner; loads once per turn, for the prompt and the tools."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        user_id: uuid.UUID,
        purpose: PlanningPurpose = "planning",
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._purpose: PlanningPurpose = purpose
        self._brief: PlanningBrief | None = None

    async def load(self) -> PlanningBrief:
        if self._brief is None:
            async with self._sessionmaker() as session:
                self._brief = await load_brief(session, self._user_id, self._purpose)
                await session.commit()  # stale mastery rows may have been rebuilt
        return self._brief

    async def scope(self) -> CardScope:
        """Nothing is in scope if the brief can't be read: cards stay within it."""
        try:
            return (await self.load()).scope()
        except Exception:
            return CardScope(kc_ids=set(), links=set())


async def load_brief(
    session: AsyncSession, user_id: uuid.UUID, purpose: PlanningPurpose = "planning"
) -> PlanningBrief:
    """May rebuild stale mastery rows first; the caller commits."""
    rules, catalog = get_rules(), get_grammar_catalog()
    result = await session.scalar(
        select(PlacementSession.result)
        .where(PlacementSession.user_id == user_id, PlacementSession.status == "done")
        .order_by(PlacementSession.finished_at.desc())
        .limit(1)
    )
    found = await candidates(
        session,
        user_id,
        rules=rules,
        catalog=catalog,
        tz=await learner_zone(session, user_id),
    )
    return PlanningBrief(
        placement=result,
        missed=await _missed(session, user_id),
        candidates=found,
        purpose=purpose,
    )


async def _missed(session: AsyncSession, user_id: uuid.UUID) -> list[MissedKC]:
    rules, catalog = get_rules(), get_grammar_catalog()
    placement = (KCEvidence.user_id == user_id, KCEvidence.source == "placement")
    # A test's answers are written in one transaction, so they share created_at.
    latest = select(func.max(KCEvidence.created_at)).where(*placement).scalar_subquery()
    wrong = set(
        (
            await session.scalars(
                select(KCEvidence.kc_id).where(
                    *placement, KCEvidence.created_at == latest, KCEvidence.correct.is_(False)
                )
            )
        ).all()
    )
    if not wrong:
        return []
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    rows = await session.execute(
        select(KCMastery.kc_id, KCMastery.p_mastery).where(
            KCMastery.user_id == user_id, KCMastery.kc_id.in_(wrong)
        )
    )
    missed = [
        MissedKC(kc, p)
        for kc_id, p in rows.all()
        if (kc := catalog.get(kc_id)) is not None and p < rules.bkt.mastered
    ]
    missed.sort(key=lambda m: (m.p_mastery, m.kc.id))
    return missed[:MISSED_SHOWN]


def render_planning(brief: PlanningBrief) -> str:
    """The planning (or daily) section of the system prompt."""
    lines = ["### Latest placement test"]
    result = brief.placement
    if result is None:
        lines.append("- None finished yet.")
    else:
        vocab, grammar = result["vocab"], result["grammar"]
        lines.append(f"- Overall level (CEFR): {result['cefr']} (the grammar level)")
        lines.append(f"- Grammar: {grammar['cefr']}, from {grammar['answered']} questions")
        size = f"- Vocabulary: about {vocab['size']} words"
        if vocab.get("reference_cefr"):
            size += f" (roughly {vocab['reference_cefr']})"
        if not vocab.get("reliable", True):
            size += "; unreliable: many made-up words were answered as known"
        lines.append(size)
    lines.append("")
    lines.append("### Grammar points missed in that test (kc_id: name, CEFR, mastery)")
    lines.extend(
        f"- `{m.kc.id}`: {m.kc.name_en}, {m.kc.cefr}, {m.p_mastery:.0%}" for m in brief.missed
    )
    if not brief.missed:
        lines.append("- None.")
    lines.append("")
    lines.append("### What the learning engine suggests now, best first")
    for c in brief.candidates:
        what = describe(c)
        if c.kc is not None:
            what = f"`{c.kc.id}`: {what}"
        lines.append(f"- {what}")
    if not brief.candidates:
        lines.append("- Nothing pressing.")
    # replace, not format: mistake examples may contain braces.
    return load_prompt(brief.purpose).replace("{planning_brief}", "\n".join(lines))
