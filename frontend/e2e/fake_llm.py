"""A tiny OpenAI-compatible chat server for Playwright (no real model, no API key).

Run from frontend/: `uv run --project ../backend python e2e/fake_llm.py`.
Replies are deterministic; a message containing "long" gets a slow ~4s reply so the
"stop generating" test has something to interrupt. It also stands in for the attachment
models (ADR 0008): structured image readings via function calling, a reply that says how
many images it was shown, /audio/transcriptions, /audio/speech for read-aloud, Bailian's
qwen-audio and qwen3-tts-flash read-aloud, and Azure's pronunciation assessment (one
word always said wrong).

Memory (ADR 0009): reflection remembers what follows "remember that" in a learner
message, and "what do you remember" gets back the facts found in the system prompt, so
tests can check which memories reached the model. Grammar tagging (ADR 0012): "he/she/it
like" is a third-person -s mistake, "he/she/it likes" a correct use of the same KC.
Word list (ADR 0011): 'what does "X" mean' makes X a word to learn. Tutor tools
(ADR 0015): with tools bound, a learner message about a word book ("词书" or "word book")
gets a streamed `propose_word_book` call, and the turn goes on with a short reply once the
tool result is back. A planning opening names the placement level; the desk pet's daily
opening (ADR 0041) says how many of the last 7 days were studied, from the brief.
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
Realtime calls (ADR 0030): /v1/realtime speaks OpenAI's Realtime protocol by a fixed
script: the tutor opens, the learner's first 1.5 s of audio is heard as a question about
"serendipity", which the tutor looks up and adds to the word list, then suggests hanging
up and says goodbye.
Workspace (ADR 0043): a paragraph's translation is "译文 " plus its first words, and a
sentence's analysis takes its first three words as the main part. With a document open,
the tutor answers 'In your document: ...'; "open it in the workspace" calls
`open_workspace` on the long text just sent (writing if the message says "writing"), and
"improve" with a writing document open calls `propose_edit` on each sentence with a
"he/she/it like" mistake. While the learner lets it open the workspace by itself (ADR
0045), "help me understand" opens the long text just sent for reading; "close the
workspace" calls `close_workspace`, "don't open the workspace by itself"
`set_workspace_auto_open` off.
"""

import asyncio
import base64
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse

PORT = int(os.environ.get("E2E_LLM_PORT", "8101"))
DELAY = float(os.environ.get("FAKE_LLM_DELAY", "0.02"))
LONG_DELAY = 0.1
# Seconds between practice drafts in a streamed set (ADR 0048): items come in one by one.
ITEM_DELAY = float(os.environ.get("FAKE_LLM_ITEM_DELAY", "0.6"))

app = FastAPI()


# What the fake "sees" in every image and "hears" in every recording.
IMAGE_TEXT = "I goed to the park yesterday."
IMAGE_DESCRIPTION = "A handwritten worksheet."
TRANSCRIPT = "I goed home yesterday."
# How long every recording is said to be: a speaking practice counts it as the learner
# talking, so two voice turns make the daily plan's 5 minutes (rules.yaml daily_plan).
SPOKEN_SECONDS = 150.0


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
# The last days in today's brief (backend/app/chat/recent.py render_recent).
DAYS_STUDIED = re.compile(r"^- Days studied: (\d+) of 7", re.MULTILINE)
# The planning brief (backend/app/chat/planning.py render_planning).
PLAN_LEVEL = re.compile(r"^- Overall level \(CEFR\): ([A-C][12])", re.MULTILINE)
WORD_BOOK = re.compile(r"词书|word book", re.IGNORECASE)
PROPOSED_BOOK = {"book_id": "oxford3000", "daily_new": 10}
# "I only have 10 minutes today": a lighter plan (backend/app/cards/tools.py ProposeDailyPlan);
# the backend lowers the counts to what is open today.
SHORT_ON_TIME = re.compile(r"只有 ?\d+ ?分钟|only have \d+ min", re.IGNORECASE)
# "Let's do flashcards": a link card to them (backend/app/cards/tools.py SuggestLink).
FLASHCARDS = re.compile(r"背单词|flashcards", re.IGNORECASE)
# Asks for the pass quiz in a lesson (ADR 0044 §4); the lesson's point is in the prompt.
QUIZ_ME = re.compile(r"测验|quiz me", re.IGNORECASE)
LESSON_POINT = re.compile(r"grammar point id ([\w.]+)\)")
# Free chat asking for questions: no id in the context, so the point goes by name (ADR 0046).
TEST_ME = re.compile(r"出点题")
# Asked in a lesson about another grammar point: the card to its lesson (ADR 0054 §1).
OTHER_POINT = re.compile(r"be 动词")
# Asks for questions, then changes their mind in the same message: the tutor gives the
# quiz card, then takes it back in the same turn (ADR 0049), naming it as its result does.
CHANGED_MIND = re.compile(r"又不想做了")
# Asks for new questions, not the unfinished quiz back (task 94).
NEW_SET = re.compile(r"换一组")
CARD_REF = re.compile(r"\(card (call_\w+)\)")
PROPOSED_PLAN = {
    "review": 0,
    "new_words": 3,
    "practice": False,
    "reading": False,
    "writing": False,
}
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
# backend/app/prompts/speaking_opening.md and backend/app/speaking/summary.py.
SPEAKING_OPENING = "has just started this speaking practice"
SPEAKING_GREETING = "Hi, I'm Sam from the design team. What's your name?"
SPOKEN_TURN = re.compile(r"^Learner: (.+)$", re.MULTILINE)


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


# The workspace (backend/app/prompts/workspace_context.md, backend/app/workspace/ai.py).
WORKSPACE_DOC = re.compile(
    r"a (reading|writing) document,\s.*?\(id ([0-9a-f-]{36}), version"
    r".*?<workspace_doc>\n(.*?)\n</workspace_doc>",
    re.DOTALL,
)
OPEN_WORKSPACE = re.compile(r"open it in the workspace", re.IGNORECASE)
IMPROVE = re.compile(r"\bimprove\b", re.IGNORECASE)
# ADR 0045: the tutor's own judgment, scripted (prompts/tutor_workspace_auto.md).
UNDERSTAND = re.compile(r"help me understand", re.IGNORECASE)
AUTO_OPEN_RULE = "The learner lets you open it by yourself"
CLOSE_WORKSPACE = re.compile(r"close the workspace", re.IGNORECASE)
AUTO_OPEN_OFF = re.compile(r"don't open the workspace by itself", re.IGNORECASE)
WORKSPACE_PARAGRAPH = "## Paragraph\n"
WORKSPACE_SENTENCE = "## Sentence\n"
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def practice_section(messages: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    """The JSON list after `title` in the last message (backend/app/adaptive/exercise/messages.py)."""
    content = text_of(messages[-1]["content"]) if messages else ""
    if title not in content:
        return []
    start = content.index(title) + len(title)
    end = content.find("\n\n", start)
    items: list[dict[str, Any]] = json.loads(content[start : end if end != -1 else None])
    return items


def rated() -> dict[str, Any]:
    return {k: {"level": v, "reason": "Typical for the level."} for k, v in RATINGS.items()}


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
# The tutor's replies to the README chat screenshot's learner (e2e/screenshots.spec.ts),
# on the demo account's weak point: present perfect vs past simple.
DEMO_CHAT = {
    "I have been to Hangzhou last month with my family.": (
        "Sounds lovely! One fix: with a finished time like **last month**, use the past "
        "simple: *I **went** to Hangzhou last month.* Keep *have been* for experiences "
        "with no time given: *I've been to Hangzhou twice.*\n\nWhat did you do there?"
    ),
    "We walked around West Lake and I have tried the Longjing tea.": (
        "West Lake in autumn is beautiful. Same point here: it was part of that trip, so "
        "*I **tried** the Longjing tea.* Ask about life so far with the present perfect: "
        "*Have you ever tried Longjing tea before?*"
    ),
}


ARTICLE_TAG = re.compile(r'<article title="([^"]*)">')


def practice_point(messages: list[dict[str, Any]]) -> str | None:
    """The grammar point named in a practice conversation's guidance, if any."""
    system = "\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")
    found = PRACTICE_POINT.search(system)
    return found.group(1) if found else None


def system_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")


def reply_for(messages: list[dict[str, Any]]) -> str:
    if messages and messages[-1]["role"] == "tool":  # the turn goes on after a tool call
        return "I've put a suggestion on a card. Confirm it if it suits you."
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    images = sum(p.get("type") == "image_url" for p in last) if isinstance(last, list) else 0
    last = text_of(last)
    if last.startswith(OPENING_CUE) and (point := practice_point(messages)):
        return f"Let's practise: {point}."
    if last.startswith(OPENING_CUE) and SPEAKING_OPENING in last:
        return SPEAKING_GREETING
    if last.startswith(OPENING_CUE) and "desk pet" in last:
        days = DAYS_STUDIED.search(system_text(messages))
        return (
            f"Good morning! You studied on {days.group(1) if days else '?'} of the last 7 days."
            " Let's review your due words today."
        )
    if last.startswith(OPENING_CUE) and "planning conversation" in last:
        level = PLAN_LEVEL.search(system_text(messages))
        return f"Your level is {level.group(1) if level else 'unknown'}. What is your goal?"
    if "<workspace_doc>" in system_text(messages):
        return f"In your document: {last}"
    if article := ARTICLE_TAG.search(system_text(messages)):  # reading_coach (Q43h)
        return f'About "{article.group(1)}": you asked {last}'
    if demo := DEMO_CHAT.get(last):
        return demo
    if "which language" in last.lower():
        if CHINESE_MODE in system_text(messages):
            return "我们主要用中文聊。"
        return "We mainly talk in English."
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
        "distractors": [
            f"It can fly ({position})",
            f"It can swim ({position})",
            f"It can sing ({position})",
        ],
        "evidence": ROVER_SENTENCE,
    }


def reading_reviews(messages: list[dict[str, Any]]) -> dict[str, Any]:
    shown = practice_section(messages, "Questions to review:\n")
    return {
        "reviews": [
            {
                "position": q["position"],
                "own_answer": next(
                    i for i, o in enumerate(q["options"]) if o.startswith("The rover")
                ),
                "answer_in_text": True,
                "one_answer": True,
                "needs_text": True,
                "content_ok": True,
                "problems": [],
            }
            for q in shown
        ]
    }


def speaking_summary(prompt: str) -> dict[str, Any]:
    """The mistake quotes what was heard ("goed"), the natural version the fixed turn;
    a quote the learner never said would be dropped by the backend."""
    said = [t.strip() for t in SPOKEN_TURN.findall(prompt)]
    heard = next((t for t in said if "goed" in t), None)
    fixed = next((t for t in said if "went home" in t), None)
    return {
        "went_well": ["你一直在用完整的句子回答。"],
        "mistakes": (
            [
                {
                    "quote": "I goed home",
                    "correction": "I went home",
                    "explanation": "go 的过去式是 went。",
                }
            ]
            if heard
            else []
        ),
        "more_natural": (
            [
                {
                    "quote": fixed,
                    "natural": "I got home yesterday.",
                    "note": "说到家时常用 got home。",
                }
            ]
            if fixed
            else []
        ),
        "next_expressions": [
            {"expression": "Nice to meet you.", "meaning": "初次见面时的客气话。"}
        ],
        "intelligibility": "mostly",
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
            f"item_{a['position']}": {
                "explanation": "The subject is third person singular, so the verb takes -s.",
                "ratings": rated(),
                **PRACTICE_DRAFTS[a["format"]],
            }
            for a in asked
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
    if name == "SpeakingSummary":
        return speaking_summary(prompt)
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
    if name == "Translation" and prompt.startswith(WORKSPACE_PARAGRAPH):
        words = prompt.removeprefix(WORKSPACE_PARAGRAPH).split()
        return {"text": "译文 " + " ".join(words[:6])}
    if name == "SentenceAnalysis" and WORKSPACE_SENTENCE in prompt:
        sentence = prompt.split(WORKSPACE_SENTENCE, 1)[1].strip()
        words = sentence.split()
        return {
            "main": " ".join(words[:3]),
            "clauses": [{"text": " ".join(words[:3]), "role": "主句的主干"}],
            "phrases": [{"text": words[-1].strip(".!?"), "meaning": "句末的词"}],
            "meaning": "句意 " + sentence,
            "tip": "先找主干。",
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
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}] if delta else [],
        **extra,
    }
    return f"data: {json.dumps(body)}\n\n"


def tutor_tool_call(
    tools: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]] | None:
    """The tool the tutor calls this time, if any: only right after a learner message."""
    names = {t["function"]["name"] for t in tools}
    if "propose_word_book" not in names or not messages:
        return None
    if messages[-1]["role"] == "tool" and "withdraw_card" in names:
        said = next(text_of(m["content"]) for m in reversed(messages) if m["role"] == "user")
        given = CARD_REF.match(text_of(messages[-1]["content"]))
        if CHANGED_MIND.search(said) and given:
            return "withdraw_card", {"card": given.group(1), "reason": "你改主意了"}
    if messages[-1]["role"] != "user":
        return None
    said = text_of(messages[-1]["content"])
    if "open_workspace" in names and OPEN_WORKSPACE.search(said):
        kind = "writing" if "writing" in said.lower() else "reading"
        return "open_workspace", {"kind": kind, "source": "last_message"}
    if "open_workspace" in names and UNDERSTAND.search(said):
        if AUTO_OPEN_RULE in system_text(messages):
            return "open_workspace", {"kind": "reading", "source": "last_message"}
    if "close_workspace" in names and CLOSE_WORKSPACE.search(said):
        return "close_workspace", {}
    if "set_workspace_auto_open" in names and AUTO_OPEN_OFF.search(said):
        return "set_workspace_auto_open", {"on": False}
    if "propose_edit" in names and IMPROVE.search(said) and (edit := proposed_edit(messages)):
        return "propose_edit", edit
    if "propose_daily_plan" in names and SHORT_ON_TIME.search(said):
        return "propose_daily_plan", PROPOSED_PLAN
    if "suggest_lesson" in names and OTHER_POINT.search(said):
        return "suggest_lesson", {"kc_id": "g.be_present"}
    if (
        "give_quiz" in names
        and QUIZ_ME.search(said)
        and (point := LESSON_POINT.search(system_text(messages)))
    ):
        return "give_quiz", {"kc_id": point.group(1), "purpose": "quiz", "asked": True}
    if "give_quiz" in names and TEST_ME.search(said):
        quiz = {"topic": "subject + verb word order", "purpose": "quiz", "asked": True}
        return "give_quiz", quiz | ({"fresh": True} if NEW_SET.search(said) else {})
    if "suggest_link" in names and FLASHCARDS.search(said):
        return "suggest_link", {"kind": "vocab_review"}
    if not WORD_BOOK.search(said):
        return None
    return "propose_word_book", PROPOSED_BOOK


def proposed_edit(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Each sentence of the open writing document with a "he/she/it like" mistake, fixed."""
    doc = WORKSPACE_DOC.search(system_text(messages))
    if not doc or doc.group(1) != "writing":
        return None
    edits = []
    for sentence in SENTENCE_END.split(doc.group(3)):
        if (third := THIRD_PERSON.search(sentence)) and not third.group(1):
            wrong = third.group(0)
            edits.append(
                {
                    "original": sentence,
                    "replacement": sentence.replace(wrong, wrong + "s", 1),
                    "reason": "Add -s to the verb after he, she or it.",
                }
            )
    return {"doc_id": doc.group(2), "edits": edits} if edits else None


def stream_tool_call(
    model: str, name: str, arguments: dict[str, Any], usage: dict[str, int]
) -> StreamingResponse:
    """The call's arguments in one chunk; a practice set's one field (item) at a time."""
    pieces = [json.dumps(arguments)]
    if name == "GeneratedItems" and arguments:
        fields = [f"{json.dumps(k)}: {json.dumps(v)}" for k, v in arguments.items()]
        pieces = ["{" + fields[0], *(", " + f for f in fields[1:]), "}"]

    async def stream() -> AsyncIterator[str]:
        call = {
            "index": 0,
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {"name": name, "arguments": pieces[0]},
        }
        yield chunk(model, {"role": "assistant", "content": None, "tool_calls": [call]})
        for piece in pieces[1:]:
            await asyncio.sleep(ITEM_DELAY)
            yield chunk(model, {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]})
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
        return stream_tool_call(model, name, tool_arguments(name, body["messages"]), usage)
    if body.get("tools") and (call := tutor_tool_call(body["tools"], body.get("messages", []))):
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
    return {"text": TRANSCRIPT, "duration": SPOKEN_SECONDS}


@app.post("/v1/audio/speech")
async def speech(request: Request) -> Response:
    """Read-aloud (ADR 0028 §3): a few bytes stand in for the mp3 (the pages under test
    play it with a made-up Audio); a model named "...-broken" is down."""
    body = await request.json()
    if "broken" in body.get("model", ""):
        return JSONResponse({"error": {"message": "speech is down"}}, status_code=503)
    return Response(f"mp3:{body['voice']}:{body['input']}".encode(), media_type="audio/mpeg")


# Bailian's qwen-audio (task 64.2a): the reading is described in a prompt, and the answer
# links to the audio, fetched in a second request. The bytes echo the prompt and seed.
QWEN_AUDIO: dict[str, bytes] = {}


@app.post("/api/v1/services/audio/tts/SpeechSynthesizer")
async def qwen_audio(request: Request) -> JSONResponse:
    if request.headers.get("authorization") != "Bearer sk-fake":
        return JSONResponse({"code": "InvalidApiKey"}, status_code=401)
    body = await request.json()
    spec = body["input"]
    clip = str(uuid.uuid4())
    QWEN_AUDIO[clip] = f"mp3:{spec['seed']}:{spec['rate']}:{spec['text_prompt']}".encode()
    url = f"{str(request.base_url).rstrip('/')}/qwen-audio/{clip}.mp3"
    return JSONResponse({"output": {"audio": {"url": url}}, "usage": {"duration": 1}})


@app.get("/qwen-audio/{clip}.mp3")
async def qwen_audio_clip(clip: str) -> Response:
    if clip not in QWEN_AUDIO:
        return Response(status_code=404)
    return Response(QWEN_AUDIO[clip], media_type="audio/mpeg")


# Bailian's qwen3-tts-flash (task 64.2b): a named voice, no speed, a link to a wav.
@app.post("/api/v1/services/aigc/multimodal-generation/generation")
async def qwen_tts(request: Request) -> JSONResponse:
    if request.headers.get("authorization") != "Bearer sk-fake":
        return JSONResponse({"code": "InvalidApiKey"}, status_code=401)
    spec = (await request.json())["input"]
    clip = str(uuid.uuid4())
    QWEN_AUDIO[clip] = f"wav:{spec['voice']}:{spec['language_type']}:{spec['text']}".encode()
    url = f"{str(request.base_url).rstrip('/')}/qwen-audio/{clip}.wav"
    usage = {"characters": len(spec["text"])}
    return JSONResponse({"output": {"audio": {"url": url}}, "usage": usage})


@app.get("/qwen-audio/{clip}.wav")
async def qwen_tts_clip(clip: str) -> Response:
    if clip not in QWEN_AUDIO:
        return Response(status_code=404)
    return Response(QWEN_AUDIO[clip], media_type="audio/wav")


# Pronunciation assessment (ADR 0028 §5): Azure's short-audio REST API, reached through an
# azure_speech connection whose base_url is this server (no ".tts." host to swap).
MISSAID = "went"  # every reading says this word wrong; it's in the e2e lexicon


@app.post("/speech/recognition/conversation/cognitiveservices/v1")
async def pronunciation(request: Request) -> dict[str, Any]:
    await request.body()
    params = json.loads(base64.b64decode(request.headers["Pronunciation-Assessment"]))
    words = re.findall(r"[A-Za-z']+", params["ReferenceText"])

    def scored(word: str) -> dict[str, Any]:
        off = word.lower() == MISSAID
        return {
            "Word": word,
            "AccuracyScore": 40 if off else 92,
            "ErrorType": "Mispronunciation" if off else "None",
            "Phonemes": [
                {"Phoneme": "w", "AccuracyScore": 85},
                {"Phoneme": "ɛ", "AccuracyScore": 20 if off else 95},
            ],
        }

    return {
        "RecognitionStatus": "Success",
        "NBest": [
            {
                "Display": params["ReferenceText"],
                "AccuracyScore": 80,
                "FluencyScore": 88,
                "CompletenessScore": 100,
                "PronScore": 84,
                "Words": [scored(w) for w in words],
            }
        ],
    }


# The model list the settings page fetches (ADR 0007 §1): an embedding and a speech model to
# check that only chat models are offered for chat, and "fake-tutor" first so it's the
# recommended one. The fake ignores model names, so fake-tutor also serves as the vision model.
MODELS = [
    "fake-tutor",
    "fake-embedding",
    "fake-tutor-mini",
    "fake-whisper",
    "fake-tts",
    "fake-realtime",
]

# A realtime call's script (ADR 0030): what the tutor says to each `response.create`.
CALL_WORD = "serendipity"
# Asked as 'what does X mean': reflection after the call must not add it back once the
# learner took it off.
CALL_LEARNER = f'What does "{CALL_WORD}" mean? Please add it to my words.'
CALL_REPLIES = [
    "Hi! What would you like to talk about?",
    f"It means finding good things by chance. I added {CALL_WORD} to your words.",
    "Great talking with you. Bye for now!",
]
# How much of the learner's audio (24 kHz PCM16) makes their one question.
CALL_HEARD_BYTES = 24000 * 2 * 3 // 2
# 0.2 s of a quiet tone, so the page has something to play.
CALL_AUDIO = base64.b64encode(
    b"".join(
        int(800 * ((i // 27) % 2 * 2 - 1)).to_bytes(2, "little", signed=True) for i in range(4800)
    )
).decode()


@app.websocket("/v1/realtime")
async def realtime(ws: WebSocket) -> None:
    await ws.accept()
    replies = 0
    heard = 0
    calls: dict[str, str] = {}  # call_id -> tool name, as results come back

    async def send(**event: Any) -> None:
        await ws.send_text(json.dumps(event))

    async def reply(text: str, tools: list[tuple[str, dict[str, str]]]) -> None:
        nonlocal replies
        replies += 1
        item = f"a{replies}"
        if text:  # a reply that only calls tools says nothing
            await send(type="response.output_audio.delta", item_id=item, delta=CALL_AUDIO)
            for i, word in enumerate(text.split(" ")):
                await send(
                    type="response.output_audio_transcript.delta",
                    item_id=item,
                    delta=word if i == 0 else f" {word}",
                )
                await asyncio.sleep(DELAY)
            await send(
                type="response.output_audio_transcript.done",
                item_id=item,
                transcript=text,
            )
        for name, arguments in tools:
            call_id = f"call-{replies}-{name}"
            calls[call_id] = name
            await send(
                type="response.output_item.done",
                item={
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            )
        await send(
            type="response.done",
            response={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    try:
        while True:
            event = json.loads(await ws.receive_text())
            kind = event.get("type")
            if kind == "session.update":
                await send(type="session.updated", session={})
            elif kind == "input_audio_buffer.append" and heard < CALL_HEARD_BYTES:
                heard += len(base64.b64decode(event.get("audio", "")))
                if heard >= CALL_HEARD_BYTES:
                    await send(type="input_audio_buffer.speech_started")
                    await send(type="input_audio_buffer.committed", item_id="u1")
                    await send(
                        type="conversation.item.input_audio_transcription.completed",
                        item_id="u1",
                        transcript=CALL_LEARNER,
                    )
                    word = {"word": CALL_WORD}
                    await reply("", [("lookup_word", word), ("add_to_vocab", word)])
            elif kind == "response.create":
                # The opening; then after each batch of tool results.
                answered = sum(1 for c in calls.values() if c == "end_session")
                if replies == 0:
                    await reply(CALL_REPLIES[0], [])
                elif answered:
                    await reply(CALL_REPLIES[2], [])
                else:
                    await reply(CALL_REPLIES[1], [("end_session", {})])
    except WebSocketDisconnect:
        return


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
