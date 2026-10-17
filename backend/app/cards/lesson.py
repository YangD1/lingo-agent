"""The lesson card (ADR 0054 §1): `suggest_lesson` points the learner to the lesson of
their grammar course on one grammar point, in a lesson conversation that went off its
point or in free chat.

Which lesson the card opens is the course's call, not the model's: a locked lesson
gives way to the earliest lesson it waits for, as the course page would.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive import course
from app.adaptive.course import Course, Lesson
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.cards.tools import CardDraft, SuggestLesson, ToolCallError, parse_args, resolve_kc

_STATES = {
    "passed": "passed",
    "review": "passed, due for review",
    "learning": "started, not passed yet",
    "available": "not started",
    "locked": "locked",
}


@dataclass(frozen=True)
class LessonResult:
    content: str
    draft: CardDraft


def opened(found: Course, lesson: Lesson) -> tuple[Lesson, int]:
    """The lesson a card for `lesson` opens, and how many locked lessons stand between:
    itself, or when it is locked, the earliest open lesson along what keeps it locked."""
    if lesson.state != "locked":
        return lesson, 0
    seen: set[str] = set()
    pending = list(lesson.blocked_by)
    while pending:
        kc_id = pending.pop()
        if kc_id in seen or (below := found.lesson(kc_id)) is None:
            continue
        seen.add(kc_id)
        pending.extend(below.blocked_by)
    reached = [o for o in found.lessons if o.kc.id in seen]
    first = next((o for o in reached if o.state in ("learning", "available")), lesson)
    return first, sum(o.state == "locked" for o in reached)


class LessonCards:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID,
        lesson_kc_id: str | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        # The lesson this conversation teaches, if it is a lesson conversation.
        self._lesson_kc_id = lesson_kc_id

    async def run(self, args: Mapping[str, Any]) -> LessonResult:
        """Raises ToolCallError, whose message goes back to the model."""
        parsed = parse_args("suggest_lesson", args)
        assert isinstance(parsed, SuggestLesson)
        kc = resolve_kc(
            "suggest_lesson",
            parsed.kc_id,
            parsed.topic,
            unmatched="try another name in English, or answer without a card",
        )
        if kc.id == self._lesson_kc_id:
            raise ToolCallError(
                f"{kc.name_en} is the lesson of this conversation: teach it here, no card"
            )
        async with self._sessionmaker() as session:
            found = await course.load(
                session,
                self._user_id,
                rules=get_rules(),
                catalog=get_grammar_catalog(),
                now=datetime.now(UTC),
            )
            await session.commit()  # stale mastery rows may have been rebuilt
        asked = found.lesson(kc.id)
        if asked is None:  # every catalog KC is in the course
            raise ToolCallError(f"{kc.name_en} is not in the learner's course")
        target, between = opened(found, asked)
        if target.kc.id == self._lesson_kc_id:
            raise ToolCallError(
                f"lesson {asked.number}, {kc.name_en}, is locked until this conversation's "
                "lesson is passed: say so, and teach this lesson first, no card"
            )
        params: dict[str, Any] = {"kc_id": target.kc.id, "number": target.number}
        content = (
            f"Card shown: lesson {target.number}, {target.kc.name_en} "
            f"({_STATES[target.state]}). It opens that lesson's conversation."
        )
        if target is not asked:
            params |= {"asked_kc_id": asked.kc.id, "asked_number": asked.number}
            content += (
                f" Lesson {asked.number}, {asked.kc.name_en}, is locked until the lessons it "
                f"builds on are passed, so the card opens lesson {target.number} first"
                + (
                    f", with {between} more lessons after it before {asked.number}"
                    if between
                    else ""
                )
                + ": tell the learner."
            )
        return LessonResult(content, CardDraft("lesson", params))
