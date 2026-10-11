"""The tutor's tools on a realtime call (ADR 0030 §4, ADR 0013, Q61a-d).

Defined once here, vendor-neutral (`{name, description, parameters}`); each adapter
puts them in its own spelling. The learner they act for comes from the call, never
from the model's arguments. A tool that fails or is refused answers with an error
result: the call goes on.

- `lookup_word`: the dictionary entry (Q61a); read-only.
- `add_to_vocab`: puts the word on the learner's list (Q61b), the way reflection
  collects words: a word they already have a card for is left alone, so adding twice
  changes nothing, and removing what a call added removes nothing else.
- `end_session`: the tutor thinks the talk is over; the learner gets a hang-up button
  and decides (Q61c).
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activity.service import (
    CollectedWord,
    HangUpSuggested,
    Step,
    Summary,
    WordLookedUp,
    WordsCollected,
)
from app.db.models import UserCard
from app.services.vocab import mine

# Chinese glosses given back: one part of speech per line in ECDICT (Q61a).
MEANINGS = 3
MAX_WORD_CHARS = 64

SPECS: list[dict[str, Any]] = [
    {
        "name": "lookup_word",
        "description": (
            "Look up an English word or short phrase in the dictionary: spelling, "
            "phonetic, Chinese meanings, and whether it is on the learner's word list. "
            "Use it when the learner asks what a word means or how to say it."
        ),
        "parameters": {
            "type": "object",
            "properties": {"word": {"type": "string", "description": "The word to look up."}},
            "required": ["word"],
        },
    },
    {
        "name": "add_to_vocab",
        "description": (
            "Put an English word on the learner's word list for review later. Only when "
            "the learner asks for it or agrees to it; never on your own."
        ),
        "parameters": {
            "type": "object",
            "properties": {"word": {"type": "string", "description": "The word to add."}},
            "required": ["word"],
        },
    },
    {
        "name": "end_session",
        "description": (
            "Suggest ending the call when the conversation has come to a natural end. "
            "The learner sees a hang-up button and decides; keep talking until they do."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]
NAMES = frozenset(spec["name"] for spec in SPECS)


class _WordArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    word: str = Field(min_length=1, max_length=MAX_WORD_CHARS)


@dataclass(frozen=True)
class Outcome:
    """What the model is told (JSON text) and what the learner is shown."""

    output: str
    # None for a tool that doesn't exist: there is nothing to show.
    step: Step | None
    # `end_session`: tell the browser to offer hanging up.
    suggest_end: bool = False


def failed(name: str, call_id: str, error: str) -> Outcome:
    return Outcome(json.dumps({"error": error}), Step(name, "failed", call_id=call_id))


class CallTools:
    def __init__(self, maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> None:
        self._maker = maker
        self._user_id = user_id

    async def run(self, name: str, call_id: str, arguments: str) -> Outcome:
        if name == "end_session":
            return Outcome(
                json.dumps(
                    {
                        "ok": True,
                        "note": "The learner now sees a hang-up button. Say goodbye "
                        "naturally; keep talking if they go on.",
                    }
                ),
                Step(name, summary=HangUpSuggested(), call_id=call_id),
                suggest_end=True,
            )
        if name not in NAMES:
            return Outcome(json.dumps({"error": "unknown tool"}), None)
        try:
            args = _WordArgs.model_validate(json.loads(arguments or "{}"))
        except (ValueError, ValidationError):
            return failed(name, call_id, 'invalid arguments: give {"word": "..."}')
        async with self._maker() as session:
            match = await mine.lookup(session, args.word)
            if match is None:
                summary: Summary = (
                    WordLookedUp(word=args.word.strip())
                    if name == "lookup_word"
                    else WordsCollected()
                )
                return Outcome(
                    json.dumps({"error": "not_found", "word": args.word.strip()}),
                    Step(name, summary=summary, call_id=call_id),
                )
            word = match.word
            if name == "lookup_word":
                on_list = await session.scalar(
                    select(UserCard.source).where(
                        UserCard.user_id == self._user_id, UserCard.word_id == word.id
                    )
                )
                return Outcome(
                    json.dumps(
                        {
                            "word": word.word,
                            "phonetic": word.phonetic or "",
                            "meanings": [
                                line.strip()
                                for line in word.translation.splitlines()
                                if line.strip()
                            ][:MEANINGS],
                            "on_word_list": on_list in mine.OWN_SOURCES,
                        },
                        ensure_ascii=False,
                    ),
                    Step(
                        name,
                        summary=WordLookedUp(word=word.word, word_id=word.id),
                        call_id=call_id,
                    ),
                )
            (collected,) = await mine.collect(session, self._user_id, [word])
        entry = CollectedWord(word_id=word.id, word=word.word)
        return Outcome(
            json.dumps({"word": word.word, "status": "added" if collected.added else "existing"}),
            Step(
                name,
                summary=WordsCollected(
                    added=[entry] if collected.added else [],
                    existing=[] if collected.added else [entry],
                ),
                call_id=call_id,
            ),
        )
