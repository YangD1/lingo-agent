"""The model picks among the candidate actions and writes the reasons (P1 plan §7.5.2).

The model proposes; code decides. An id not among the candidates, or a repeat, is
dropped, so the model cannot invent a link or a grammar point. When fewer than three
survive, the best remaining candidates fill in with template text (Q18d), which the
page renders in the learner's language with live numbers.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.advice.candidates import Candidate
from app.db.models import UserProfile
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm

ADVICE_TASK = "advice"
MAX_ITEMS = 3
MAX_TITLE_CHARS = 80
MAX_REASON_CHARS = 300
# Per mistake example given to the model.
MAX_EXAMPLE_CHARS = 200


class DraftItem(BaseModel):
    candidate_id: str = Field(description="The id of one candidate, copied exactly")
    title: str = Field(description="A short call to action")
    reason: str = Field(description="One or two sentences on why, without exact numbers")


class AdviceDraft(BaseModel):
    items: list[DraftItem] = Field(description="At most three, best first")


@dataclass(frozen=True, slots=True)
class Item:
    candidate_id: str
    # None: template text, rendered by the page in the learner's language.
    title: str | None = None
    reason: str | None = None


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def accept(draft: AdviceDraft, candidates: Sequence[Candidate]) -> list[Item]:
    """The model's items that name a candidate, once each, cleaned up."""
    known = {c.id for c in candidates}
    items: list[Item] = []
    for d in draft.items:
        title, reason = _clip(d.title, MAX_TITLE_CHARS), _clip(d.reason, MAX_REASON_CHARS)
        if d.candidate_id not in known or not title or not reason:
            continue
        if any(item.candidate_id == d.candidate_id for item in items):
            continue
        items.append(Item(d.candidate_id, title, reason))
    return items[:MAX_ITEMS]


def fill(items: Sequence[Item], candidates: Sequence[Candidate]) -> list[Item]:
    """Keeps `items` that are still candidates; the best others fill in, as templates."""
    known = {c.id for c in candidates}
    kept = [item for item in items if item.candidate_id in known][:MAX_ITEMS]
    used = {item.candidate_id for item in kept}
    spare = [Item(c.id) for c in candidates if c.id not in used]
    return kept + spare[: MAX_ITEMS - len(kept)]


def _quote(text: str) -> str:
    return '"' + _clip(text, MAX_EXAMPLE_CHARS).replace('"', "'") + '"'


def describe(c: Candidate) -> str:
    """One candidate in plain English, with its evidence."""
    match c.kind:
        case "placement":
            if c.days_since is None:
                what = "Take the placement test: never taken"
            else:
                what = f"Retake the placement test: last taken {c.days_since} days ago"
            if c.in_progress:
                what += " (a test is in progress, can be continued)"
            return what
        case "choose_book":
            return "Choose a word book: none chosen yet"
        case "vocab_screen":
            name = c.book.name_en if c.book else "the word book"
            return f"Mark the words already known in {name}: not screened yet"
        case "vocab_review":
            return f"Review words that are due: {c.count} due"
        case "vocab_learn":
            name = f" from {c.book.name_en}" if c.book else ""
            return f"Learn today's new words{name}: {c.count} left today"
        case "grammar_practice":
            assert c.kc is not None
            p = c.p_mastery if c.p_mastery is not None else 0.0
            what = (
                f'Practise the grammar point "{c.kc.name_en}" ({c.kc.cefr}): mastery {p:.0%}, '
                f"{c.count} mistakes in recent conversations"
            )
            for e in c.examples:
                fixed = f" -> {_quote(e.correction)}" if e.correction else ""
                what += f"\n  - mistake: {_quote(e.original)}{fixed}"
            return what


def render_input(
    candidates: Sequence[Candidate], profile: UserProfile | None, language: str
) -> str:
    lines = [f"Write in: {language}", "", "## Learner profile"]
    fields = {
        "Level (CEFR)": profile.cefr_level if profile else None,
        "Goal": profile.goal if profile else None,
        "Target exam": profile.target_exam if profile else None,
        "Minutes a day": profile.daily_minutes if profile else None,
        "Interests": ", ".join(profile.interests) if profile and profile.interests else None,
    }
    known = [f"- {name}: {value}" for name, value in fields.items() if value]
    lines.extend(known or ["(nothing known yet)"])
    lines.extend(["", "## Candidates"])
    lines.extend(f"- `{c.id}`: {describe(c)}" for c in candidates)
    return "\n".join(lines)


async def write(
    ctx: TenantProviderContext,
    candidates: Sequence[Candidate],
    profile: UserProfile | None,
    *,
    language: str,
    config: RunnableConfig,
) -> list[Item]:
    """The model's picks, checked; may be fewer than three. Raises if the call fails."""
    llm = get_structured_llm(ctx, ADVICE_TASK, AdviceDraft)
    draft = await llm.ainvoke(
        [
            SystemMessage(load_prompt("advice")),
            HumanMessage(render_input(candidates, profile, language)),
        ],
        config=config,
    )
    return accept(draft, candidates)
