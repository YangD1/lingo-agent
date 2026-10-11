"""A realtime call's transcript order and marks (Q61e, Q61f)."""

from app.providers.openai_realtime import Subtitle
from app.realtime.transcript import INTERRUPTED, MAX_WAITING, VOICE_CALL, Transcript


def texts(lines: list) -> list[tuple[str, str]]:  # type: ignore[type-arg]
    return [(line.role, line.text) for line in lines]


def test_a_learner_turn_keeps_its_place_until_its_subtitle_comes() -> None:
    transcript = Transcript()
    transcript.learner_turn("u1")
    transcript.subtitle(Subtitle("tutor", "a1", "Hi", final=False))
    transcript.subtitle(Subtitle("tutor", "a1", "Hi there!", final=True))
    assert transcript.take_settled() == []
    transcript.subtitle(Subtitle("learner", "u1", "Hel", final=False))
    transcript.subtitle(Subtitle("learner", "u1", "Hello", final=True))
    assert texts(transcript.take_settled()) == [("learner", "Hello"), ("tutor", "Hi there!")]
    assert transcript.take_settled() == []


def test_talking_over_a_reply_keeps_what_had_come() -> None:
    transcript = Transcript()
    transcript.subtitle(Subtitle("tutor", "a1", "Let ", final=False))
    transcript.subtitle(Subtitle("tutor", "a1", "me", final=False))
    transcript.speech_started()
    transcript.subtitle(Subtitle("tutor", "a1", "Let me tell you a story.", final=True))
    (line,) = transcript.take_settled()
    assert line.text == "Let me" and line.interrupted
    message = line.message()
    assert message.type == "ai" and message.additional_kwargs == {
        VOICE_CALL: True,
        INTERRUPTED: True,
    }


def test_a_reply_ends_with_its_response() -> None:
    transcript = Transcript()
    transcript.subtitle(Subtitle("tutor", "a1", "Sure", final=False))
    transcript.response_done("completed")
    transcript.subtitle(Subtitle("tutor", "a2", "Well", final=False))
    transcript.response_done("cancelled")
    first, second = transcript.take_settled()
    assert (first.text, first.interrupted) == ("Sure", False)
    assert (second.text, second.interrupted) == ("Well", True)


def test_empty_turns_are_dropped_and_a_lost_one_stops_holding_back() -> None:
    transcript = Transcript()
    transcript.learner_turn("u0")  # noise: transcribed to nothing
    transcript.subtitle(Subtitle("learner", "u0", " ", final=True))
    transcript.learner_turn("u1")  # never transcribed
    for n in range(MAX_WAITING):
        transcript.subtitle(Subtitle("tutor", f"a{n}", f"line {n}", final=True))
    settled = transcript.take_settled()
    assert [text for _, text in texts(settled)] == [f"line {n}" for n in range(MAX_WAITING)]
    transcript.subtitle(Subtitle("learner", "u2", "late", final=False))
    assert texts(transcript.take_all()) == [("learner", "late")]


def test_learner_messages_are_human_messages() -> None:
    transcript = Transcript()
    transcript.subtitle(Subtitle("learner", "u1", " Hello ", final=True))
    (line,) = transcript.take_settled()
    message = line.message()
    assert (message.type, message.text, message.id) == ("human", "Hello", line.message_id)
    assert message.additional_kwargs == {VOICE_CALL: True}
