import base64
import uuid

import pytest

from app.attachments import context
from app.attachments.context import TurnAttachment, TurnImage, render_turn, turn_content


def att(kind: str, text: str, filename: str = "f", **meta: object) -> TurnAttachment:
    return TurnAttachment(uuid.uuid4(), kind, "x/y", filename, text, dict(meta))


def test_text_without_attachments_is_unchanged() -> None:
    assert render_turn("Hi", []) == "Hi"


def test_attachments_follow_the_text_with_labels() -> None:
    rendered = render_turn(
        "Can you check this?",
        [
            att("image", "Text in the image:\nI goed", "hw.jpg"),
            att("document", "Essay body", "e.pdf"),
        ],
    )

    assert rendered == (
        "Can you check this?\n\n"
        '[Attachment 1: image "hw.jpg"]\nText in the image:\nI goed\n\n'
        '[Attachment 2: document "e.pdf"]\nEssay body'
    )


def test_a_voice_transcript_is_not_repeated() -> None:
    transcript = "I goed home yesterday."
    assert render_turn(transcript, [att("audio", transcript)]) == (
        f"{transcript}\n\n[Attachment 1: voice message, transcript]\n"
        "(the message above is this transcript)"
    )
    # If the learner edited the text, both are shown.
    assert "I goed home" in render_turn("Is this right?", [att("audio", transcript)])


def test_documents_share_a_per_turn_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context, "MAX_TURN_DOCUMENT_CHARS", 10)

    rendered = render_turn("", [att("document", "0123456", "a"), att("document", "abcdef", "b")])

    assert rendered == (
        '[Attachment 1: document "a"]\n0123456\n\n'
        '[Attachment 2: document "b", only its first 3 characters are included]\nabc'
    )


def test_extraction_cut_is_reported_even_within_budget() -> None:
    rendered = render_turn("", [att("document", "short", "big.pdf", truncated=True)])
    assert rendered.startswith('[Attachment 1: document "big.pdf", only its first 5 characters')


def test_images_become_standard_image_blocks() -> None:
    content = turn_content("Look", [TurnImage(b"\xff\xd8jpeg", "image/jpeg")])

    assert content == [
        {"type": "text", "text": "Look"},
        {
            "type": "image",
            "base64": base64.b64encode(b"\xff\xd8jpeg").decode(),
            "mime_type": "image/jpeg",
        },
    ]
    assert turn_content("Only text", []) == "Only text"
    assert turn_content("", [TurnImage(b"x", "image/jpeg")])[0] == {
        "type": "text",
        "text": "(see the attached image)",
    }
