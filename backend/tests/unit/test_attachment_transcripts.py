"""Which transcripts count as nothing heard (task 20.5.2)."""

import pytest

from app.attachments.handlers import heard_speech


@pytest.mark.parametrize(
    "text",
    [
        "I goed home yesterday.",
        "Yes.",
        "天气怎么样",
        "Hmm",
        "aaaah, I don't know",  # repeats, but well under the share
        "12",
    ],
)
def test_speech_is_kept(text: str) -> None:
    assert heard_speech(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n",
        "...",
        "♪ ♪",
        "ლლლლლლლლლლლლლლლლ",  # what whisper made of a -60 dB clip
        "ლ ლ ლ ლ ლ ლ ლ ლ ლ ლ ლ ლ",  # spaces don't dilute the share
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
    ],
)
def test_empty_or_hallucinated_transcripts_are_dropped(text: str) -> None:
    assert not heard_speech(text)
