import asyncio
import base64
import io
import uuid
from typing import Any

import docx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda

from app.attachments import handlers, reading
from app.attachments.reading import ImageReading
from app.providers.asr import Transcript, TranscriptionError
from app.providers.config import TenantProviderContext
from tests.integration.test_attachments_api import png, settled, uploaded
from tests.integration.test_chat_api import login, new_conversation
from tests.unit.test_attachment_documents import scanned_pdf, text_pdf


class FakeVision:
    """Stands in for the tenant's vision route; records what it was shown."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[list[BaseMessage], RunnableConfig | None]] = []
        self.fail_on_call = fail_on_call
        self.active = 0
        self.peak = 0

    async def __call__(self, messages: list[BaseMessage], config: RunnableConfig) -> ImageReading:
        self.calls.append((messages, config))
        number = len(self.calls)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if number == self.fail_on_call:
            error = RuntimeError("vendor said sk-secret")
            error.status_code = 503  # type: ignore[attr-defined]
            raise error
        return ImageReading(text_in_image=f"I goed home ({number})", description="A worksheet.")


@pytest.fixture
def vision(monkeypatch: pytest.MonkeyPatch) -> FakeVision:
    fake = FakeVision()

    def get_structured_llm(ctx: TenantProviderContext, task: str, schema: Any) -> Any:
        assert (task, schema) == ("vision", ImageReading)
        return RunnableLambda(fake)

    monkeypatch.setattr(reading, "get_structured_llm", get_structured_llm)
    return fake


class FakeASR:
    def __init__(
        self, error: Exception | None = None, text: str = "I goed home yesterday."
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error
        self.text = text

    async def transcribe(self, audio: bytes, **kwargs: Any) -> Transcript:
        self.calls.append({"audio": audio, **kwargs})
        if self.error is not None:
            raise self.error
        return Transcript(self.text, "en", 2.5)


def use_asr(monkeypatch: pytest.MonkeyPatch, fake: FakeASR) -> FakeASR:
    monkeypatch.setattr(handlers, "get_asr", lambda ctx: fake)
    return fake


async def test_image_is_read_by_the_vision_model(
    client: AsyncClient, app: FastAPI, vision: FakeVision
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], png(), "hw.png")

    ready = await settled(client, app, created["id"])

    assert ready["status"] == "ready"
    assert ready["text"] == "Description: A worksheet.\n\nText in the image:\nI goed home (1)"
    assert ready["meta"]["reading"] == {
        "text_in_image": "I goed home (1)",
        "description": "A worksheet.",
    }
    ((messages, config),) = vision.calls
    system, human = messages
    assert "Never correct mistakes" in system.text
    image_block = human.content[1]
    assert isinstance(image_block, dict)
    assert image_block["type"] == "image" and image_block["mime_type"] == "image/jpeg"
    content = await client.get(f"/attachments/{created['id']}/content")
    assert base64.b64decode(image_block["base64"]) == content.content  # the normalized JPEG
    assert config is not None and config["metadata"]["conversation_id"] == conversation["id"]


async def test_image_without_a_vision_model_explains_what_to_set_up(
    client: AsyncClient, app: FastAPI
) -> None:
    await login(client)  # no connections at all
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], png(), "hw.png")

    failed = await settled(client, app, created["id"])

    assert (failed["status"], failed["error"]) == ("failed", "no_vision_model")
    assert "vision" in failed["meta"]["error_message"]


async def test_vision_errors_show_the_status_but_not_the_vendor_text(
    client: AsyncClient, app: FastAPI, vision: FakeVision
) -> None:
    vision.fail_on_call = 1
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], png(), "hw.png")

    failed = await settled(client, app, created["id"])

    assert (failed["status"], failed["error"]) == ("failed", "vision_failed")
    assert "HTTP 503" in failed["meta"]["error_message"]
    assert "sk-secret" not in failed["meta"]["error_message"]


async def test_audio_is_transcribed(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    asr = use_asr(monkeypatch, FakeASR())
    await login(client)
    conversation = await new_conversation(client)
    audio = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
    created = await uploaded(client, conversation["id"], audio, "voice.webm")

    ready = await settled(client, app, created["id"])

    assert (ready["kind"], ready["mime_type"]) == ("audio", "audio/webm")
    assert ready["text"] == "I goed home yesterday."
    assert ready["meta"] == {"language": "en", "duration_seconds": 2.5, "progress": None}
    (call,) = asr.calls
    assert call["audio"] == audio
    assert (call["filename"], call["mime_type"]) == ("voice.webm", "audio/webm")
    assert call["conversation_id"] == uuid.UUID(conversation["id"])


async def test_audio_without_asr_or_with_a_failing_asr(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    audio = b"OggS" + b"\x00" * 64

    not_configured = await uploaded(client, conversation["id"], audio, "a.ogg")
    assert (await settled(client, app, not_configured["id"]))["error"] == "no_asr_model"

    cause = RuntimeError("sk-secret")
    cause.status_code = 429  # type: ignore[attr-defined]
    error = TranscriptionError("all failed")
    error.__cause__ = cause
    use_asr(monkeypatch, FakeASR(error))
    failing = await uploaded(client, conversation["id"], audio, "b.ogg")
    failed = await settled(client, app, failing["id"])
    assert failed["error"] == "transcription_failed"
    assert "HTTP 429" in failed["meta"]["error_message"]


async def test_audio_with_nothing_heard_fails(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_asr(monkeypatch, FakeASR(text="ლლლლლლლლლლლლლლ"))
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"OggS" + b"\x00" * 64, "quiet.ogg")

    failed = await settled(client, app, created["id"])

    assert failed["status"] == "failed"
    assert failed["error"] == "transcription_empty"
    assert failed["text"] is None


async def test_text_pdf_needs_no_model(client: AsyncClient, app: FastAPI) -> None:
    await login(client)  # no vision model: text pages must not need one
    conversation = await new_conversation(client)
    data = text_pdf(["First page of the article.", "Second page of the article."])
    created = await uploaded(client, conversation["id"], data, "article.pdf")

    ready = await settled(client, app, created["id"])

    assert ready["status"] == "ready"
    assert ready["text"] == (
        "[Page 1]\nFirst page of the article.\n\n[Page 2]\nSecond page of the article."
    )
    assert ready["meta"]["pages"] == 2 and ready["meta"]["scanned_pages"] == 0


async def test_scanned_pdf_pages_are_read_with_bounded_concurrency(
    client: AsyncClient, app: FastAPI, vision: FakeVision
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], scanned_pdf(6, (600, 800)), "scan.pdf")

    ready = await settled(client, app, created["id"])

    assert ready["status"] == "ready", ready
    assert ready["meta"]["pages"] == 6 and ready["meta"]["scanned_pages"] == 6
    assert ready["meta"]["progress"] is None
    # Every page read once, in page order in the text whatever order they finished in.
    assert len(vision.calls) == 6
    assert ready["text"].startswith("[Page 1]\nI goed home (")
    assert ready["text"].count("[Page ") == 6
    assert 1 < vision.peak <= 4  # the processor's shared vision slots


async def test_scanned_pdf_reports_progress(
    client: AsyncClient, app: FastAPI, vision: FakeVision
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    seen: list[Any] = []
    original = FakeVision.__call__

    async def slow(self: FakeVision, messages: Any, config: Any) -> ImageReading:
        response = await client.get(f"/attachments/{created['id']}")
        seen.append(response.json()["meta"].get("progress"))
        return await original(self, messages, config)

    FakeVision.__call__ = slow  # type: ignore[method-assign]
    try:
        created = await uploaded(client, conversation["id"], scanned_pdf(2, (300, 400)), "s.pdf")
        await settled(client, app, created["id"])
    finally:
        FakeVision.__call__ = original  # type: ignore[method-assign]

    assert {"done": 0, "total": 2} in seen


async def test_one_failed_page_fails_the_pdf_with_its_reason(
    client: AsyncClient, app: FastAPI, vision: FakeVision
) -> None:
    vision.fail_on_call = 2
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], scanned_pdf(3, (300, 400)), "s.pdf")

    failed = await settled(client, app, created["id"])

    assert (failed["status"], failed["error"]) == ("failed", "vision_failed")


async def test_scanned_pdf_without_a_vision_model(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], scanned_pdf(1, (300, 400)), "s.pdf")

    failed = await settled(client, app, created["id"])

    assert failed["error"] == "no_vision_model"


async def test_word_documents_are_extracted(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    document = docx.Document()
    document.add_paragraph("Dear Sir, I am writing to complain.")
    out = io.BytesIO()
    document.save(out)
    created = await uploaded(client, conversation["id"], out.getvalue(), "letter.docx")

    ready = await settled(client, app, created["id"])

    assert ready["text"] == "Dear Sir, I am writing to complain."
    assert ready["mime_type"].endswith("wordprocessingml.document")


async def test_long_documents_are_truncated(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(handlers, "MAX_DOCUMENT_CHARS", 10)
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"0123456789abcdef", "long.txt")

    ready = await settled(client, app, created["id"])

    assert ready["text"] == "0123456789"
    assert ready["meta"]["truncated"] is True and ready["meta"]["chars"] == 10
