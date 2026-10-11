"""A realtime call's transcript (ADR 0030 §6, Q61e, Q61f).

Both sides' final subtitles become the call's conversation, a turn at a time, so a
restart loses at most the turn being spoken. Order comes from the turns, not from the
subtitles: the learner's transcript is made by a separate model and often arrives
after the tutor has started answering. A learner turn is placed when the vendor commits
it (`LearnerTurn`); a subtitle for a turn never announced goes at the end.

A tutor reply the learner talks over is kept as far as its text had come, marked
`interrupted` (Q61f); text arriving for it afterwards is ignored.
"""

import uuid
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.providers.realtime_session import Role, Subtitle

# Marks on the saved messages (`additional_kwargs`).
VOICE_CALL = "voice_call"
INTERRUPTED = "interrupted"
# A learner turn whose subtitle never comes stops holding back the turns after it once
# this many are waiting (the hang-up saves everything anyway).
MAX_WAITING = 6


@dataclass
class Line:
    role: Role
    item_id: str
    text: str = ""
    final: bool = False
    interrupted: bool = False
    # The saved message's id: tool activity is attached to it (task 61.2).
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def message(self) -> BaseMessage:
        marks: dict[str, bool] = {VOICE_CALL: True}
        if self.interrupted:
            marks[INTERRUPTED] = True
        text = self.text.strip()
        if self.role == "learner":
            return HumanMessage(content=text, id=self.message_id, additional_kwargs=marks)
        return AIMessage(content=text, id=self.message_id, additional_kwargs=marks)


class Transcript:
    def __init__(self) -> None:
        self._lines: list[Line] = []
        # The learner's latest turn: tool activity is shown under it.
        self._turn_id: str | None = None

    def learner_turn(self, item_id: str) -> None:
        if self._find(item_id) is None:
            self._add(Line("learner", item_id))

    def subtitle(self, event: Subtitle) -> None:
        line = self._find(event.item_id)
        if line is None:
            line = self._add(Line(event.role, event.item_id))
        if line.final:
            return
        if event.final:
            line.text, line.final = event.text, True
        else:
            line.text += event.text

    def turn_id(self) -> str:
        """The message the tutor's tool calls belong to: the learner's latest turn, or
        before they have said anything, the tutor's first line."""
        if self._turn_id is None:
            self._turn_id = str(uuid.uuid4()) if not self._lines else self._lines[0].message_id
        return self._turn_id

    def speech_started(self) -> None:
        """The learner talked over the tutor: a reply still coming ends here."""
        for line in self._lines:
            if line.role == "tutor" and not line.final:
                line.final = line.interrupted = True

    def response_done(self, status: str) -> None:
        """A reply ended: its text is all there is. One cut short ends `cancelled`."""
        for line in self._lines:
            if line.role == "tutor" and not line.final:
                line.final = True
                line.interrupted = status == "cancelled"

    def take_settled(self) -> list[Line]:
        """The finished lines at the front, in order, with text; they are taken out."""
        count = 0
        for line in self._lines:
            if not line.final and len(self._lines) - count <= MAX_WAITING:
                break
            count += 1
        return self._take(count)

    def take_all(self) -> list[Line]:
        """Everything left with any text (the call is over)."""
        return self._take(len(self._lines))

    def _take(self, count: int) -> list[Line]:
        taken, self._lines = self._lines[:count], self._lines[count:]
        return [line for line in taken if line.text.strip()]

    def _add(self, line: Line) -> Line:
        self._lines.append(line)
        if line.role == "learner":
            self._turn_id = line.message_id
        return line

    def _find(self, item_id: str) -> Line | None:
        return next((line for line in self._lines if line.item_id == item_id), None)
