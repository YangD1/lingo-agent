"""Which model of a fallback chain wrote a practice item (exercises.model)."""

import uuid

from langchain_core.outputs import LLMResult

from app.adaptive.exercise.worker import _AnsweredBy


def test_the_model_that_answered_last_is_kept() -> None:
    handler = _AnsweredBy()
    failed, answered = uuid.uuid4(), uuid.uuid4()
    for run_id, connection in ((failed, "main"), (answered, "backup")):
        handler.on_chat_model_start(
            {},
            [],
            run_id=run_id,
            tags=["task:exercise_generate", f"connection:{connection}", "kind:openai"],
            metadata={"ls_model_name": f"{connection}-model"},
        )
    handler.on_llm_end(LLMResult(generations=[]), run_id=answered)

    assert handler.model == "backup:backup-model"


def test_unknown_runs_leave_it_unset() -> None:
    handler = _AnsweredBy()
    run_id = uuid.uuid4()
    handler.on_chat_model_start({}, [], run_id=run_id, tags=None, metadata=None)
    handler.on_llm_end(LLMResult(generations=[]), run_id=run_id)

    assert handler.model is None
