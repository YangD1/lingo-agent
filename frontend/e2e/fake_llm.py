"""A tiny OpenAI-compatible chat server for Playwright (no real model, no API key).

Run from frontend/: `uv run --project ../backend python e2e/fake_llm.py`.
Replies are deterministic; a message containing "long" gets a slow ~4s reply so the
"stop generating" test has something to interrupt. It also stands in for the attachment
models (ADR 0008): structured image readings via function calling, a reply that says how
many images it was shown, and /audio/transcriptions.

Memory (ADR 0009): reflection remembers what follows "remember that" in a learner
message, and "what do you remember" gets back the facts found in the system prompt, so
tests can check which memories reached the model. Grammar tagging (ADR 0012): "he/she/it
like" is a third-person -s mistake, "he/she/it likes" a correct use of the same KC.
Word list (ADR 0011): 'what does "X" mean' makes X a word to learn. Study advice
(P1 plan §7.5.2): an invented action first, then a grammar practice candidate if there
is one, else the last candidate, so tests can check that only real candidates survive.
"""

import asyncio
import json
import os
import re
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


# New learner messages are rendered as "Learner [u1]: ...".
LEARNER_LINE = re.compile(r"^Learner(?: \[(u\d+)\])?: (.*)$", re.MULTILINE)
REMEMBER = re.compile(r"remember that (.+?)\.?$", re.IGNORECASE)
THIRD_PERSON = re.compile(r"\b(?:he|she|it) like(s?)\b", re.IGNORECASE)
THIRD_PERSON_KC = "g.present_simple_third_person"
ASKED_WORD = re.compile(r"what does \"?([A-Za-z]+)\"? mean", re.IGNORECASE)
FACTS_HEADING = "### Things they have told you\n"
# Advice candidates are listed as "- `<id>`: <what>".
CANDIDATE_LINE = re.compile(r"^- `([^`]+)`:", re.MULTILINE)


def text_of(content: Any) -> str:
    if isinstance(content, list):  # content parts
        return " ".join(p.get("text", "") for p in content)
    return str(content or "")


def remembered_facts(messages: list[dict[str, Any]]) -> list[str]:
    system = "\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")
    if FACTS_HEADING not in system:
        return []
    block = system.split(FACTS_HEADING, 1)[1].split("\n\n", 1)[0]
    return [line.removeprefix("- ") for line in block.splitlines()]


def reply_for(messages: list[dict[str, Any]]) -> str:
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    images = sum(p.get("type") == "image_url" for p in last) if isinstance(last, list) else 0
    last = text_of(last)
    if "what do you remember" in last.lower():
        return "I remember: " + (" | ".join(remembered_facts(messages)) or "nothing yet")
    if "long" in last.lower():
        return " ".join(f"word{i}" for i in range(40))
    seen = f"I can see {images} image(s). " if images else ""
    return f"Nice try! {seen}You said: {last}"


def reflection(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Post-turn memory reflection: one fact per "remember that ..." among the new messages."""
    prompt = text_of(messages[-1]["content"]) if messages else ""
    new = prompt.split("## New messages to reflect on", 1)[-1]
    facts: list[str] = []
    mistakes: list[dict[str, Any]] = []
    used: list[dict[str, str]] = []
    words: list[dict[str, str]] = []
    for line in LEARNER_LINE.finditer(new):
        message_id, text = line.group(1), line.group(2)
        if remember := REMEMBER.search(text):
            facts.append(remember.group(1).strip())
        if message_id:
            words += [{"message": message_id, "word": w} for w in ASKED_WORD.findall(text)]
        if message_id and (third := THIRD_PERSON.search(text)):
            if third.group(1):
                used.append({"message": message_id, "kc_id": THIRD_PERSON_KC})
            else:
                mistakes.append(
                    {
                        "message": message_id,
                        "kc_id": THIRD_PERSON_KC,
                        "error_type": "omission",
                        "severity": "medium",
                        "original": third.group(0),
                        "correction": third.group(0) + "s",
                    }
                )
    return {
        "memory_ops": [{"action": "add", "content": f"{f[0].upper()}{f[1:]}."} for f in facts],
        "mistakes": mistakes,
        "used_correctly": used,
        "vocab_candidates": words,
    }


def advice(messages: list[dict[str, Any]]) -> dict[str, Any]:
    ids = CANDIDATE_LINE.findall(text_of(messages[-1]["content"]) if messages else "")
    grammar = [i for i in ids if i.startswith("grammar_practice:")]
    picked = grammar[0] if grammar else ids[-1]
    return {
        "items": [
            {"candidate_id": "invented_action", "title": "Made up", "reason": "Not a candidate."},
            {"candidate_id": picked, "title": "趁热练一练", "reason": "假模型挑了这一条。"},
        ]
    }


def tool_arguments(name: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Canned arguments for the schema (function) asked for; otherwise an image reading."""
    if name == "Reflection":
        return reflection(messages)
    if name == "AdviceDraft":
        return advice(messages)
    if name == "EpisodeSummary":
        return {"summary": "The learner practised small talk."}
    return {"text_in_image": IMAGE_TEXT, "description": IMAGE_DESCRIPTION}


def tool_reply(
    model: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> JSONResponse:
    """Structured output via function calling."""
    name = tools[0]["function"]["name"]
    arguments = tool_arguments(name, messages)
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
        return tool_reply(model, body["tools"], body.get("messages", []))
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
