"""writing_coach's review of the text a learner sent in free chat (Q38b, task 38.5).

The turn always reviews the learner's message, without the model deciding to: the
same service as `/writing` (`app/writing/service.py`) stores it as a submission of
this conversation, the worker reviews it while the turn waits, and a card links the
learner to the line-by-line review. The coach is then told the result, to comment on
briefly.

Bound at the API layer to the learner, conversation and turn, like the tutor's tools.
"""

import uuid
from dataclasses import dataclass, replace
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activity.service import ActivityStatus, WritingReviewed
from app.adaptive.kc.catalog import get_grammar_catalog
from app.cards import service as cards
from app.cards.tools import CardDraft
from app.db.models import WritingSubmission
from app.prompts import load_prompt
from app.writing import service
from app.writing.worker import WritingWorker

# How long the turn waits for the review; a slower one finishes in the background
# and the card shows it when it is done.
WAIT_SECONDS = 90
# Corrections listed for the coach; the card has them all.
MAX_LISTED = 8


@dataclass(frozen=True)
class WritingOutcome:
    """What the coach is told, the card shown and the step recorded."""

    guidance: str
    status: ActivityStatus
    # None when no submission was made (failed steps carry no summary anyway).
    summary: WritingReviewed | None
    card: dict[str, Any] | None = None


class WritingSource(Protocol):
    async def review(self, text: str) -> WritingOutcome: ...


class DatabaseWriting:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        worker: WritingWorker,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        turn_id: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._worker = worker
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._conversation_id = conversation_id
        self._turn_id = turn_id

    async def review(self, text: str) -> WritingOutcome:
        async with self._sessionmaker() as session:
            try:
                row = await service.create(
                    session, self._user_id, text=text, conversation_id=self._conversation_id
                )
            except service.LengthError:
                return failed()
            submission_id = row.id
            await session.commit()
        self._worker.submit(submission_id, self._user_id, self._tenant_id)
        await self._worker.wait(submission_id, at_most=WAIT_SECONDS)
        async with self._sessionmaker() as session:
            reviewed = await service.get(session, self._user_id, submission_id)
            if reviewed is None:  # deleted while it was being reviewed
                return failed()
            card = await cards.put_card(
                session,
                user_id=self._user_id,
                conversation_id=self._conversation_id,
                turn_id=self._turn_id,
                tool_call_id=f"writing-{submission_id}",
                draft=CardDraft("writing", {"submission_id": submission_id}),
            )
            return outcome(reviewed, cards.card_json(card))


def failed() -> WritingOutcome:
    """The review could not be done; the coach replies on its own."""
    return WritingOutcome(
        guidance=load_prompt("writing_coach").replace("{review}", load_prompt("writing_failed")),
        status="failed",
        summary=None,
    )


def outcome(row: WritingSubmission, card: dict[str, Any] | None) -> WritingOutcome:
    """The coach's guidance for a submission as it stands after the wait."""
    if row.status == "failed":
        return replace(failed(), card=card)
    if row.status != "done":
        return WritingOutcome(
            guidance=load_prompt("writing_coach").replace(
                "{review}", load_prompt("writing_pending")
            ),
            status="ok",
            summary=WritingReviewed(submission_id=row.id),
            card=card,
        )
    mistakes = [m for s in row.corrections or [] for m in s["mistakes"]]
    return WritingOutcome(
        guidance=load_prompt("writing_coach").replace("{review}", render_review(row)),
        status="ok",
        summary=WritingReviewed(submission_id=row.id, mistakes=len(mistakes)),
        card=card,
    )


def render_review(row: WritingSubmission) -> str:
    catalog = get_grammar_catalog()
    lines = [
        "The learner sees the whole review, sentence by sentence, on a card under your "
        "reply; point them to it for the rest.",
        f"Overall: {row.summary or ''}".strip(),
    ]
    scores = row.scores or {}
    if scores:
        lines.append("Scores (1 to 5):")
        lines.extend(
            f"- {name}: {score['score']} ({score['reason']})" for name, score in scores.items()
        )
    mistakes = [m for s in row.corrections or [] for m in s["mistakes"]]
    if mistakes:
        lines.append(f"Corrections ({len(mistakes)} in all, the most important first):")
        order = {"high": 0, "medium": 1, "low": 2}
        ranked = sorted(mistakes, key=lambda m: order.get(m["severity"], 3))
        for m in ranked[:MAX_LISTED]:
            kc = catalog.get(m["kc_id"])
            point = kc.name_en if kc else m["kc_id"]
            lines.append(
                f'- "{m["original"]}" -> "{m["correction"]}" ({point}): {m["explanation"]}'
            )
    else:
        lines.append("No grammar mistakes were found.")
    return "\n".join(lines)
