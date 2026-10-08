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
Word list (ADR 0011): 'what does "X" mean' makes X a word to learn. Tutor tools
(ADR 0015): with tools bound, a learner message about a word book ("词书" or "word book")
gets a streamed `propose_word_book` call, and the turn goes on with a short reply once the
tool result is back. A planning opening names the placement level.
Language mix (ADR 0017): "which language" gets back the language the system prompt asks
for; AI example sentences use the word asked for; a translation into Chinese is "译文 "
plus the message, one into English "(English) " plus it.
Practice sets (ADR 0021): the generator writes the same item per format whatever the
grammar point, the critic passes them all answering as the key does, and the grader
marks an open answer wrong with "walk" -> "walks" as another mistake (an answer equal
to the reference is graded by code and never reaches it).
Writing (ADR 0023): a long free-chat message that asks to "review my writing" is routed
to writing_coach, anything else to the tutor; the review marks each "he/she/it like" as
a third-person -s mistake and puts the words written in double quotes on the word list.
Reading (ADR 0024): an article is rewritten as ~300 words about a rover, with "ubiquitous"
and "serendipity" past A2 for the glossary, and five questions whose right option starts
"The rover"; the critic picks that option, so every question passes. reading_coach
answers 'About "<the article's title>"', so tests can see the article reached it.
"""

import asyncio
import json
import os
import re
import time
import uuid
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
# A practice opening (backend/app/prompts/practice_opening.md) and the point it is about
# (backend/app/chat/practice.py render_practice).
OPENING_CUE = "(This is not from the learner.)"
PRACTICE_POINT = re.compile(r"^- Grammar point: (.+) \(CEFR [A-C][12]\)$", re.MULTILINE)
ASKED_WORD = re.compile(r"what does \"?([A-Za-z]+)\"? mean", re.IGNORECASE)
FACTS_HEADING = "### Things they have told you\n"
# The planning brief (backend/app/chat/planning.py render_planning).
PLAN_LEVEL = re.compile(r"^- Overall level \(CEFR\): ([A-C][12])", re.MULTILINE)
WORD_BOOK = re.compile(r"词书|word book", re.IGNORECASE)
PROPOSED_BOOK = {"book_id": "oxford3000", "daily_new": 10}
# backend/app/prompts/language_zh.md; the examples and translation inputs.
CHINESE_MODE = "mainly in Chinese"
EXAMPLE_WORD = re.compile(r"^Word: (.+)$", re.MULTILINE)
TRANSLATE_TARGET = re.compile(r"^Target language: (.+)$", re.MULTILINE)
# backend/app/agents/routing.py classify and backend/app/writing/review.py review_messages.
ROUTE_MESSAGE = "## Learner's message\n"
WRITING_ASK = re.compile(r"review my writing", re.IGNORECASE)
NUMBERED_SENTENCE = re.compile(r"^\[(\d+)\] (.+)$", re.MULTILINE)
QUOTED_WORD = re.compile(r'"([A-Za-z]+)"')
# A mistake in the diagnosis context (backend/app/adaptive/diagnosis/context.py render).
DIAGNOSIS_EVIDENCE = re.compile(r"^\s*- evidence (\d+) \(", re.MULTILINE)
DIAGNOSIS_HYPOTHESIS = "主语是第三人称单数时，你常常漏掉动词的 -s。"  # noqa: RUF001


# Practice items per format (backend/app/adaptive/exercise/drafts.py Draft) and the key
# the critic answers with (own_answer, own_segment).
PRACTICE_DRAFTS: dict[str, dict[str, Any]] = {
    "choice4": {
        "stem": "My brother ___ in a hospital.",
        "options": ["works", "work", "working", "is work"],
        "correct": "works",
    },
    "cloze": {
        "stem": "She ___ coffee every morning.",
        "hint": "drink",
        "accepted": ["drinks"],
    },
    "find_fix": {
        "segments": ["He ", "go ", "to work."],
        "wrong_segment": 1,
        "accepted": ["goes "],
    },
    "transform": {
        "instruction": "Start with 'My sister'.",
        "source": "I play tennis.",
        "accepted": ["My sister plays tennis."],
    },
    "translate": {"source": "她走路上班。", "accepted": ["She walks to work."]},
    "rewrite_own": {
        "instruction": "Correct the sentence.",
        "accepted": ["She likes music."],
    },
}
PRACTICE_KEYS: dict[str, tuple[str, int | None]] = {
    "choice4": ("works", None),
    "cloze": ("drinks", None),
    "find_fix": ("goes ", 1),
    "transform": ("My sister plays tennis.", None),
    "translate": ("She walks to work.", None),
    "rewrite_own": ("She likes music.", None),
}
# One level per rubric dimension (backend/app/adaptive/rules.yaml difficulty.dimensions);
# the generator and the critic agree, so no item fails on difficulty.
RATINGS = {
    "vocabulary": "at_target",
    "syntax": "moderate",
    "cues": "partial",
    "distractors": "one_plausible",
}


def practice_section(
    messages: list[dict[str, Any]], title: str
) -> list[dict[str, Any]]:
    """The JSON list after `title` in the last message (backend/app/adaptive/exercise/messages.py)."""
    content = text_of(messages[-1]["content"]) if messages else ""
    if title not in content:
        return []
    start = content.index(title) + len(title)
    end = content.find("\n\n", start)
    items: list[dict[str, Any]] = json.loads(
        content[start : end if end != -1 else None]
    )
    return items


def rated() -> dict[str, Any]:
    return {
        k: {"level": v, "reason": "Typical for the level."} for k, v in RATINGS.items()
    }


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


# reading_coach's article (backend/app/prompts/reading_coach.md).
ARTICLE_TAG = re.compile(r'<article title="([^"]*)">')


def practice_point(messages: list[dict[str, Any]]) -> str | None:
    """The grammar point named in a practice conversation's guidance, if any."""
    system = "\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")
    found = PRACTICE_POINT.search(system)
    return found.group(1) if found else None


def system_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")


def reply_for(messages: list[dict[str, Any]]) -> str:
    if (
        messages and messages[-1]["role"] == "tool"
    ):  # the turn goes on after a tool call
        return "I've put a suggestion on a card. Confirm it if it suits you."
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    images = (
        sum(p.get("type") == "image_url" for p in last) if isinstance(last, list) else 0
    )
    last = text_of(last)
    if last.startswith(OPENING_CUE) and (point := practice_point(messages)):
        return f"Let's practise: {point}."
    if last.startswith(OPENING_CUE) and "planning conversation" in last:
        level = PLAN_LEVEL.search(system_text(messages))
        return f"Your level is {level.group(1) if level else 'unknown'}. What is your goal?"
    if article := ARTICLE_TAG.search(system_text(messages)):  # reading_coach (Q43h)
        return f"About \"{article.group(1)}\": you asked {last}"
    if "which language" in last.lower():
        if CHINESE_MODE in system_text(messages):
            return "我们主要用中文聊。"
        return "We mainly talk in English."
    if "what do you remember" in last.lower():
        return "I remember: " + (
            " | ".join(remembered_facts(messages)) or "nothing yet"
        )
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
            words += [
                {"message": message_id, "word": w} for w in ASKED_WORD.findall(text)
            ]
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
        "memory_ops": [
            {"action": "add", "content": f"{f[0].upper()}{f[1:]}."} for f in facts
        ],
        "mistakes": mistakes,
        "used_correctly": used,
        "vocab_candidates": words,
    }


def writing_review(prompt: str) -> dict[str, Any]:
    """A review of the numbered sentences: only those with a mistake, fixed scores."""
    sentences: list[dict[str, Any]] = []
    for line in NUMBERED_SENTENCE.finditer(prompt):
        index, text = int(line.group(1)), line.group(2)
        if not (third := THIRD_PERSON.search(text)) or third.group(1):
            continue
        wrong = third.group(0)
        sentences.append(
            {
                "index": index,
                "corrected": text.replace(wrong, wrong + "s", 1),
                "mistakes": [
                    {
                        "kc_id": THIRD_PERSON_KC,
                        "error_type": "omission",
                        "severity": "medium",
                        "original": wrong,
                        "correction": wrong + "s",
                        "explanation": "Add -s to the verb after he, she or it.",
                    }
                ],
            }
        )
    score = {"score": 3, "reason": "Fine for the level."}
    return {
        "sentences": sentences,
        "scores": {k: score for k in ("task", "coherence", "vocabulary", "grammar")},
        "summary": "A clear piece of writing; watch the verb endings.",
        "vocab_candidates": QUOTED_WORD.findall(prompt),
    }


# The rewrite (backend/app/services/reading/drafts.py ArticleRewrite): five paragraphs,
# 295 words, inside A2's 250-400.
ROVER_SENTENCE = "The rover can go far and run on the ubiquitous red sand."
ROVER_TEXT = [
    " ".join([ROVER_SENTENCE] * 4 + ["It was found by serendipity, and the team was very happy."]),
] * 5


def reading_question(position: int) -> dict[str, Any]:
    return {
        "position": position,
        "question": f"Question {position}: what can the rover do?",
        "correct": f"The rover can go far ({position})",
        "distractors": [f"It can fly ({position})", f"It can swim ({position})", f"It can sing ({position})"],
        "evidence": ROVER_SENTENCE,
    }


def reading_reviews(messages: list[dict[str, Any]]) -> dict[str, Any]:
    shown = practice_section(messages, "Questions to review:\n")
    return {
        "reviews": [
            {
                "position": q["position"],
                "own_answer": next(i for i, o in enumerate(q["options"]) if o.startswith("The rover")),
                "answer_in_text": True,
                "one_answer": True,
                "needs_text": True,
                "content_ok": True,
                "problems": [],
            }
            for q in shown
        ]
    }


def tool_arguments(name: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Canned arguments for the schema (function) asked for; otherwise an image reading."""
    if name == "Reflection":
        return reflection(messages)
    if name == "ArticleRewrite":
        return {
            "title": "Rover news",
            "paragraphs": ROVER_TEXT,
            "questions": [reading_question(p) for p in range(1, 6)],
        }
    if name == "QuestionSet":
        asked = practice_section(messages, "write a new one for each position:\n")
        return {"questions": [reading_question(a["position"]) for a in asked]}
    if name == "QuestionReviews":
        return reading_reviews(messages)
    if name == "EpisodeSummary":
        return {"summary": "The learner practised small talk."}
    if name == "GeneratedItems":
        asked = practice_section(messages, "Items to write:\n")
        return {
            "items": [
                {
                    "position": a["position"],
                    "format": a["format"],
                    "explanation": "The subject is third person singular, so the verb takes -s.",
                    "ratings": rated(),
                    **PRACTICE_DRAFTS[a["format"]],
                }
                for a in asked
            ]
        }
    if name == "CriticReport":
        items = practice_section(messages, "Items to review:\n")
        return {
            "reviews": [
                {
                    "position": i["position"],
                    "own_answer": PRACTICE_KEYS[i["format"]][0],
                    "own_segment": PRACTICE_KEYS[i["format"]][1],
                    "answer_ok": True,
                    "tests_kc": True,
                    "content_ok": True,
                    "problems": [],
                    "ratings": rated(),
                }
                for i in items
            ]
        }
    if name == "Graded":
        return {
            "correct": False,
            "explanation": "The verb needs -s after a third-person subject.",
            "corrected": "She walks to work.",
            "other_mistakes": [
                {
                    "kc_id": THIRD_PERSON_KC,
                    "error_type": "omission",
                    "severity": "medium",
                    "original": "walk",
                    "correction": "walks",
                }
            ],
        }
    prompt = text_of(messages[-1]["content"]) if messages else ""
    if name == "RouteDecision":
        message = prompt.split(ROUTE_MESSAGE, 1)[-1]
        return {"route": "writing_coach" if WRITING_ASK.search(message) else "tutor"}
    if name == "Review":
        return writing_review(prompt)
    if name == "DiagnosisOut":
        # One cause on the third-person -s, citing every mistake shown.
        return {
            "root_causes": [
                {
                    "hypothesis": DIAGNOSIS_HYPOTHESIS,
                    "kc_ids": [THIRD_PERSON_KC],
                    "evidence_ids": [int(i) for i in DIAGNOSIS_EVIDENCE.findall(prompt)],
                    "confidence": "high",
                    "suggestion": "用 he / she 各说三句日常习惯。",
                }
            ]
        }
    if name == "WordExamples" and (word := EXAMPLE_WORD.search(prompt)):
        w = word.group(1)
        return {
            "sentences": [
                {"en": f"I {w} every day.", "zh": f"我每天都 {w}。"},
                {"en": f"Do you {w} often?", "zh": f"你经常 {w} 吗"},
            ]
        }
    if name == "Translation" and (target := TRANSLATE_TARGET.search(prompt)):
        message = prompt.split("## Message\n", 1)[-1]
        chinese = target.group(1) != "English"
        return {"text": ("译文 " if chinese else "(English) ") + message}
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
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments),
                                },
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
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}]
        if delta
        else [],
        **extra,
    }
    return f"data: {json.dumps(body)}\n\n"


def tutor_tool_call(
    tools: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]] | None:
    """The tool the tutor calls this time, if any: only right after a learner message."""
    names = {t["function"]["name"] for t in tools}
    if (
        "propose_word_book" not in names
        or not messages
        or messages[-1]["role"] != "user"
    ):
        return None
    if not WORD_BOOK.search(text_of(messages[-1]["content"])):
        return None
    return "propose_word_book", PROPOSED_BOOK


def stream_tool_call(
    model: str, name: str, arguments: dict[str, Any], usage: dict[str, int]
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        call = {
            "index": 0,
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }
        yield chunk(model, {"role": "assistant", "content": None, "tool_calls": [call]})
        yield chunk(model, {}, usage=usage)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/v1/chat/completions", response_model=None)
async def completions(request: Request) -> StreamingResponse | JSONResponse:
    body = await request.json()
    model = body.get("model", "fake")
    if body.get("tools") and not body.get("stream"):
        return tool_reply(model, body["tools"], body.get("messages", []))
    if body.get("tools") and body.get("tool_choice") not in (None, "auto"):
        # Structured output inside the chat graph is streamed (routing.classify).
        name = body["tools"][0]["function"]["name"]
        usage = {"prompt_tokens": 42, "completion_tokens": 10, "total_tokens": 52}
        return stream_tool_call(
            model, name, tool_arguments(name, body["messages"]), usage
        )
    if body.get("tools") and (
        call := tutor_tool_call(body["tools"], body.get("messages", []))
    ):
        usage = {"prompt_tokens": 42, "completion_tokens": 10, "total_tokens": 52}
        return stream_tool_call(model, *call, usage)
    text = reply_for(body.get("messages", []))
    usage = {
        "prompt_tokens": 42,
        "completion_tokens": len(text.split()),
        "total_tokens": 0,
    }
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
