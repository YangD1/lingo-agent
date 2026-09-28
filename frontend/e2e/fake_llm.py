"""A tiny OpenAI-compatible chat server for Playwright (no real model, no API key).

Run from frontend/: `uv run --project ../backend python e2e/fake_llm.py`.
Replies are deterministic; a message containing "long" gets a slow ~4s reply so the
"stop generating" test has something to interrupt.
"""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

PORT = int(os.environ.get("E2E_LLM_PORT", "8101"))
DELAY = float(os.environ.get("FAKE_LLM_DELAY", "0.02"))
LONG_DELAY = 0.1

app = FastAPI()


def reply_for(messages: list[dict[str, Any]]) -> str:
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if isinstance(last, list):  # content parts
        last = " ".join(p.get("text", "") for p in last)
    if "long" in last.lower():
        return " ".join(f"word{i}" for i in range(40))
    return f"Nice try! You said: {last}"


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


# The model list the settings page fetches (ADR 0007 §1): one embedding model to check that
# only chat models are offered, and "fake-tutor" first so it's the recommended one.
MODELS = ["fake-tutor", "fake-embedding", "fake-tutor-mini"]


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
