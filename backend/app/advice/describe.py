"""Candidate actions in plain English, for the tutor's system prompt (ADR 0016).

The dashboard's and the planning conversation's prompts list what the learning engine
suggests; the tutor talks about these and may only offer cards within them.
"""

from app.advice.candidates import Candidate

# Per mistake example given to the model.
MAX_EXAMPLE_CHARS = 200


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


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
