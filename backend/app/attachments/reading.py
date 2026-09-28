"""Turning an image into text with the tenant's `vision` route (ADR 0008 §1)."""

import base64

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.attachments.processor import ProcessingFailed, ProcessingJob
from app.prompts import load_prompt
from app.providers.errors import NoModelConfiguredError
from app.providers.llm import get_structured_llm


class ImageReading(BaseModel):
    text_in_image: str = Field(
        description="All legible text exactly as written, mistakes included; empty if none."
    )
    description: str = Field(description="What the image shows, briefly, in English.")


def render_reading(reading: ImageReading) -> str:
    """The derived text the conversation sees for an image."""
    parts = []
    if reading.description.strip():
        parts.append(f"Description: {reading.description.strip()}")
    if reading.text_in_image.strip():
        parts.append(f"Text in the image:\n{reading.text_in_image.strip()}")
    return "\n\n".join(parts)


def vendor_failure(exc: BaseException) -> str:
    """A reason safe to show: the HTTP status if there is one, never the vendor's text
    (it can echo request details)."""
    status = getattr(exc, "status_code", None)
    return f"HTTP {status}" if isinstance(status, int) else type(exc).__name__


async def read_image(
    job: ProcessingJob, image: bytes, mime_type: str, *, instruction: str = "Read this image."
) -> ImageReading:
    try:
        llm = get_structured_llm(await job.provider_context(), "vision", ImageReading)
    except NoModelConfiguredError as exc:
        raise ProcessingFailed(
            exc.code, "no image-capable model is configured; set the vision route in Settings"
        ) from exc
    messages = [
        SystemMessage(load_prompt("image_reading")),
        HumanMessage(
            content=[
                {"type": "text", "text": instruction},
                {
                    "type": "image",
                    "base64": base64.b64encode(image).decode("ascii"),
                    "mime_type": mime_type,
                },
            ]
        ),
    ]
    config: RunnableConfig = {
        # llm_usage attributes the call to the learner and conversation (ADR 0005).
        "metadata": {"user_id": str(job.user_id), "conversation_id": str(job.conversation_id)},
        "tags": ["attachment"],
    }
    async with job.vision_slots:
        try:
            return await llm.ainvoke(messages, config=config)
        except Exception as exc:
            raise ProcessingFailed(
                "vision_failed", f"the vision model failed ({vendor_failure(exc)})"
            ) from exc
