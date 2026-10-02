"""The model an evaluator calls: replayed from a cassette, or real (Q36a, Q36b).

A recording is keyed by the task, the messages and the output schema, so any change
to a prompt, to what code puts in the messages or to a schema makes replay miss, and
the run fails asking for a re-recording instead of grading new prompts with old
answers.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm

CASSETTES_DIR = Path(__file__).parent / "cassettes"

RERECORD_HINT = "make eval-live ARGS='--email <account> --record'"


class EvalModel(Protocol):
    async def structured[T: BaseModel](
        self, case_id: str, task: str, schema: type[T], messages: Sequence[BaseMessage]
    ) -> T: ...


def call_key(task: str, schema: type[BaseModel], messages: Sequence[BaseMessage]) -> str:
    payload = {
        "task": task,
        "schema": schema.model_json_schema(),
        "messages": [{"type": m.type, "content": m.content} for m in messages],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class CassetteMiss(LookupError):
    def __init__(self, dataset: str, case_id: str, task: str) -> None:
        super().__init__(
            f"{dataset}/{case_id}: no recording of this {task} call. A prompt, the messages "
            f"or the schema changed since it was recorded; re-record with {RERECORD_HINT}"
        )


@dataclass
class Cassette:
    """Recorded outputs of one dataset: `cassettes/<dataset>.json`."""

    path: Path
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, dataset: str, directory: Path = CASSETTES_DIR) -> "Cassette":
        path = directory / f"{dataset}.json"
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(path, entries)

    @property
    def dataset(self) -> str:
        return self.path.stem

    def add(self, case_id: str, task: str, key: str, output: BaseModel) -> None:
        output_json = output.model_dump(mode="json")
        self.entries[key] = {"case": case_id, "task": task, "output": output_json}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.entries, ensure_ascii=False, indent=1, sort_keys=True)
        self.path.write_text(text + "\n", encoding="utf-8")


class ReplayModel:
    def __init__(self, cassette: Cassette) -> None:
        self.cassette = cassette

    async def structured[T: BaseModel](
        self, case_id: str, task: str, schema: type[T], messages: Sequence[BaseMessage]
    ) -> T:
        entry = self.cassette.entries.get(call_key(task, schema, messages))
        if entry is None:
            raise CassetteMiss(self.cassette.dataset, case_id, task)
        return schema.model_validate(entry["output"])


class LiveModel:
    """The tenant's own models through the provider layer. With `record_to`, every
    output is added to that cassette; record into an empty one and save it after a
    full run, so recordings no case makes any more do not linger."""

    def __init__(self, ctx: TenantProviderContext, record_to: Cassette | None = None) -> None:
        self.ctx = ctx
        self.record_to = record_to

    async def structured[T: BaseModel](
        self, case_id: str, task: str, schema: type[T], messages: Sequence[BaseMessage]
    ) -> T:
        output = await get_structured_llm(self.ctx, task, schema).ainvoke(list(messages))
        if self.record_to is not None:
            self.record_to.add(case_id, task, call_key(task, schema, messages), output)
        return output
