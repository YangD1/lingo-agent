"""A tiny OpenAI-compatible chat server for Playwright (no real model, no API key).

Run from frontend/: `uv run --project ../backend python e2e/fake_llm.py`.
Replies are deterministic; a message containing "long" gets a slow ~4s reply so the
"stop generating" test has something to interrupt. It also stands in for the attachment
models (ADR 0008): structured image readings via function calling, a reply that says how
many images it was shown, and /audio/transcriptions.
"""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

PORT = int(os.environ.get("E2E_LLM_PORT", "8101"))
DELAY = float(os.environ.get("FAKE_LLM_DELAY", "0.02"))
LONG_DELAY = 0.1

app = FastAPI()


# What the fake "sees" in every image and "hears" in every recording.
IMAGE_TEXT = "I goed to the park yesterday."
IMAGE_DESCRIPTION = "A handwritten worksheet."
TRANSCRIPT = "I goed home yesterday."


def reply_for(messages: list[dict[str, Any]]) -> str:
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    images = 0
    if isinstance(last, list):  # content parts
        images = sum(p.get("type") == "image_url" for p in last)
        last = " ".join(p.get("text", "") for p in last)
    if "long" in last.lower():
        return " ".join(f"word{i}" for i in range(40))
    seen = f"I can see {images} image(s). " if images else ""
    return f"Nice try! {seen}You said: {last}"


def tool_reply(model: str, tools: list[dict[str, Any]]) -> JSONResponse:
    """Structured output via function calling: always the same image reading."""
    name = tools[0]["function"]["name"]
    arguments = {"text_in_image": IMAGE_TEXT, "description": IMAGE_DESCRIPTION}
    return JSONResponse(
        {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_fake",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(arguments)},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 42, "completion_tokens": 10, "total_tokens": 52},
        }
    )


def chunk(model: str, delta: dict[str, Any], **extra: Any) -> str:
    body = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}] if delta else [],
        **extra,
    }
    return f"data: {json.dumps(body)}\n\n"


@app.post("/v1/chat/completions", response_model=None)
async def completions(request: Request) -> StreamingResponse | JSONResponse:
    body = await request.json()
    model = body.get("model", "fake")
    if body.get("tools") and not body.get("stream"):
        return tool_reply(model, body["tools"])
    text = reply_for(body.get("messages", []))
    usage = {"prompt_tokens": 42, "completion_tokens": len(text.split()), "total_tokens": 0}
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

    if not body.get("stream"):
        return JSONResponse(
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }
        )

    delay = LONG_DELAY if text.startswith("word0") else DELAY

    async def stream() -> AsyncIterator[str]:
        yield chunk(model, {"role": "assistant", "content": ""})
        for i, word in enumerate(text.split(" ")):
            await asyncio.sleep(delay)
            yield chunk(model, {"content": word if i == 0 else f" {word}"})
        if (body.get("stream_options") or {}).get("include_usage"):
            yield chunk(model, {}, usage=usage)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/v1/audio/transcriptions")
async def transcriptions(file: UploadFile) -> dict[str, Any]:
    await file.read()
    return {"text": TRANSCRIPT}


# The model list the settings page fetches (ADR 0007 §1): an embedding and a speech model to
# check that only chat models are offered for chat, and "fake-tutor" first so it's the
# recommended one. The fake ignores model names, so fake-tutor also serves as the vision model.
MODELS = ["fake-tutor", "fake-embedding", "fake-tutor-mini", "fake-whisper"]


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
