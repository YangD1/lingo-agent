"""The workspace reading view's model calls (ADR 0043 §4): translation and analysis."""

from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkspaceAnnotation
from app.workspace import ai
from app.workspace.ai import Clause, Phrase, SentenceAnalysis, Translation
from tests.integration.test_chat_send import connect, login, new_conversation
from tests.integration.test_word_popup_api import FakeStructured

TEXT = (
    "The plan, which the council approved last week, will cut costs.\n\n"
    "Nobody expected it to pass so quickly."
)
SENTENCE = "The plan, which the council approved last week, will cut costs."


class FakeTranslator(FakeStructured):
    """Answers each paragraph with a marked copy, so results can be told apart."""

    def __init__(self) -> None:
        super().__init__(None)

    async def ainvoke(self, messages: list[Any], config: Any = None) -> Any:
        await super().ainvoke(messages, config)
        return Translation(text="译 " + str(messages[-1].content).split("\n", 1)[1])


async def open_doc(client: AsyncClient, kind: str = "reading", text: str = TEXT) -> str:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    response = await client.post(
        f"/conversations/{conversation_id}/workspace",
        json={"kind": kind, "source": "paste", "text": text},
    )
    doc_id: str = response.json()["id"]
    return doc_id


async def translate(client: AsyncClient, doc_id: str, *paragraphs: int) -> Response:
    return await client.post(
        f"/workspace/docs/{doc_id}/translate", json={"paragraphs": list(paragraphs)}
    )


async def test_paragraphs_are_translated_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client)
    fake = FakeTranslator()
    monkeypatch.setattr(ai, "get_structured_llm", fake)

    first = await translate(client, doc_id, 1)
    assert first.status_code == 200, first.text
    assert first.json() == {
        "version": 1,
        "translations": [{"index": 1, "text": "译 Nobody expected it to pass so quickly."}],
    }
    assert fake.task == "translate" and fake.calls == 1

    # Both now: only the first paragraph is new.
    both = (await translate(client, doc_id, 0, 1, 1)).json()["translations"]
    assert [t["index"] for t in both] == [0, 1]
    assert both[0]["text"].startswith("译 The plan")
    assert fake.calls == 2


async def test_an_edited_paragraph_is_translated_again(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client)
    fake = FakeTranslator()
    monkeypatch.setattr(ai, "get_structured_llm", fake)
    await translate(client, doc_id, 0, 1)
    saved = await client.put(
        f"/workspace/docs/{doc_id}/content",
        json={
            "base_version": 1,
            "paragraphs": ["Changed first.", "Nobody expected it to pass so quickly."],
        },
    )
    assert saved.status_code == 200
    again = (await translate(client, doc_id, 0, 1)).json()
    assert again["version"] == 2
    assert again["translations"][0]["text"] == "译 Changed first."
    assert fake.calls == 3  # the unchanged paragraph came from the cache


async def test_translation_needs_a_model_and_a_real_paragraph(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    doc_id = (
        await client.post(
            f"/conversations/{conversation_id}/workspace",
            json={"kind": "reading", "source": "paste", "text": TEXT},
        )
    ).json()["id"]
    no_model = await translate(client, doc_id, 0)
    assert no_model.status_code == 409
    assert no_model.json()["detail"]["code"] == "no_llm_configured"

    monkeypatch.setattr(ai, "get_structured_llm", FakeTranslator())
    assert (await translate(client, doc_id, 2)).status_code == 404
    assert (await translate(client, doc_id)).status_code == 422
    assert (await translate(client, doc_id, *range(7))).status_code == 422


async def test_a_failed_call_keeps_nothing(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client)
    monkeypatch.setattr(ai, "get_structured_llm", FakeStructured(RuntimeError("vendor")))
    response = await translate(client, doc_id, 0)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "llm_unavailable"
    assert await db_session.scalar(select(func.count()).select_from(WorkspaceAnnotation)) == 0


async def test_writing_documents_have_no_paragraphs_to_translate(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client, kind="writing")
    monkeypatch.setattr(ai, "get_structured_llm", FakeTranslator())
    response = await translate(client, doc_id, 0)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "workspace_not_reading"


ANALYSIS = SentenceAnalysis(
    main="The plan … will cut costs",
    clauses=[
        Clause(text="which the council approved last week", role="定语从句 修饰 the plan"),
        Clause(text="which nobody wrote", role="made up"),
    ],
    phrases=[Phrase(text="cut costs", meaning="降低成本"), Phrase(text="red tape", meaning="x")],
    meaning="上周议会批准的这项计划将降低成本。",
    tip="主语和谓语被从句隔开了。",
)


async def analyze(client: AsyncClient, doc_id: str, sentence: str, paragraph: int = 0) -> Response:
    return await client.post(
        f"/workspace/docs/{doc_id}/analyze", json={"paragraph": paragraph, "sentence": sentence}
    )


async def test_a_sentence_is_analysed_once_and_checked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client)
    fake = FakeStructured(ANALYSIS)
    monkeypatch.setattr(ai, "get_structured_llm", fake)

    response = await analyze(client, doc_id, f"  {SENTENCE} ")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "main": "The plan … will cut costs",
        # What the sentence doesn't have is dropped.
        "clauses": [
            {"text": "which the council approved last week", "role": "定语从句 修饰 the plan"}
        ],
        "phrases": [{"text": "cut costs", "meaning": "降低成本"}],
        "meaning": "上周议会批准的这项计划将降低成本。",
        "tip": "主语和谓语被从句隔开了。",
    }
    assert fake.task == "sentence_analysis"
    assert "Explanation language: Simplified Chinese" in fake.prompts[0]
    assert "## Sentence\n" + SENTENCE in fake.prompts[0]
    assert (await analyze(client, doc_id, SENTENCE)).json() == response.json()
    assert fake.calls == 1


async def test_analysis_follows_the_explanation_language(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client)
    await client.patch("/profile", json={"explanation_language": "en"})
    fake = FakeStructured(ANALYSIS)
    monkeypatch.setattr(ai, "get_structured_llm", fake)
    await analyze(client, doc_id, SENTENCE)
    assert "Explanation language: English" in fake.prompts[0]


async def test_only_sentences_of_the_document_are_analysed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client)
    fake = FakeStructured(ANALYSIS)
    monkeypatch.setattr(ai, "get_structured_llm", fake)
    elsewhere = await analyze(client, doc_id, "Write me a poem about the sea.")
    assert elsewhere.status_code == 404
    assert elsewhere.json()["detail"]["code"] == "workspace_sentence_not_found"
    # In the document, but not in that paragraph.
    assert (await analyze(client, doc_id, SENTENCE, paragraph=1)).status_code == 404
    assert (await analyze(client, doc_id, SENTENCE, paragraph=5)).status_code == 404
    assert fake.calls == 0


async def test_an_empty_analysis_is_not_kept(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client)
    empty = ANALYSIS.model_copy(update={"meaning": " "})
    monkeypatch.setattr(ai, "get_structured_llm", FakeStructured(empty))
    response = await analyze(client, doc_id, SENTENCE)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "analysis_invalid"
    assert await db_session.scalar(select(func.count()).select_from(WorkspaceAnnotation)) == 0


MARKDOWN = (
    "## Street trees\n"
    "- Trees give **shade** on [hot days](https://example.com).\n"
    "- They clean the air.\n\n"
    "```\nplant(tree)\n```"
)


async def test_a_markdown_paste_keeps_its_blocks(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client, text=MARKDOWN)
    doc = (await client.get(f"/workspace/docs/{doc_id}")).json()
    assert doc["title"] == "Street trees"
    assert doc["content"]["paragraphs"] == [
        "## Street trees",
        "- Trees give **shade** on [hot days](https://example.com).\n- They clean the air.",
        "```\nplant(tree)\n```",
    ]

    # Translated with its marks (the prompt says to keep them); a code block as it is,
    # with no call (Q84c).
    fake = FakeTranslator()
    monkeypatch.setattr(ai, "get_structured_llm", fake)
    translations = (await translate(client, doc_id, 1, 2)).json()["translations"]
    assert translations[0]["text"].startswith("译 - Trees give **shade**")
    assert translations[1] == {"index": 2, "text": "```\nplant(tree)\n```"}
    assert fake.calls == 1
    assert "keep every mark" in ai.load_prompt("workspace_translate")


async def test_a_sentence_of_a_markdown_block_is_analysed_without_its_marks(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await open_doc(client, text=MARKDOWN)
    fake = FakeStructured(ANALYSIS)
    monkeypatch.setattr(ai, "get_structured_llm", fake)
    # The view sends the sentence as shown in analysis mode: no marks (Q84b).
    response = await analyze(client, doc_id, "Trees give shade on hot days.", paragraph=1)
    assert response.status_code == 200, response.text
    assert "## Paragraph\nTrees give shade on hot days. They clean the air.\n" in fake.prompts[0]
    # Not a way round the check.
    assert (await analyze(client, doc_id, "Trees give hot days.", paragraph=1)).status_code == 404
