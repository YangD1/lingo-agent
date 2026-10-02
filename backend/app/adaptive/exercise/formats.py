"""Exercise formats (ADR 0021 §1): what each kind of practice item contains.

One model per format holds the item as the generator writes it: `content` is what the
learner sees, `answer` stays on the server until they answer. The same models check the
generator's structured output, the JSONB columns of `exercises` and the API, so a
malformed item is rejected wherever it comes from. `SPECS` says how each format is
graded and which evidence an answer to it yields.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.adaptive.placement.items import BLANK
from app.adaptive.rules import Evidence

Format = Literal["choice4", "cloze", "find_fix", "transform", "translate", "rewrite_own"]
FORMATS: tuple[Format, ...] = get_args(Format)

# code: compared with the answer key. model: judged by `exercise_grade`.
# code_then_model: the key first, the model only for answers the key does not list.
Grading = Literal["code", "code_then_model", "model"]

Text = Annotated[str, Field(min_length=1, max_length=400)]
Explanation = Annotated[str, Field(min_length=1, max_length=1000)]
# Every answer that counts as right; for open formats the first is the reference answer.
Accepted = Annotated[tuple[Text, ...], Field(min_length=1, max_length=8)]

# Curly quotes, as phone keyboards type them.
_QUOTES = str.maketrans({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})


def normalize(text: str) -> str:
    """The form answers are compared in: case, spacing, quote style and a final stop
    do not matter; anything else (a wrong ending, a missing article) does."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).casefold()
    return re.sub(r"\s+", " ", text).strip().rstrip(".!?").strip()


def _distinct(texts: tuple[str, ...]) -> bool:
    return len({normalize(t) for t in texts}) == len(texts)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_blank(stem: str) -> None:
    if stem.count(BLANK) != 1:
        raise ValueError(f"stem must contain exactly one {BLANK}")


# --- choice4: pick the option that fills the gap (the placement item shape) ---


class Choice4Content(_Strict):
    stem: Text
    # Shown in this order; the generator's order is shuffled before saving.
    options: tuple[Text, Text, Text, Text]


class Choice4Answer(_Strict):
    correct: Text
    explanation: Explanation


class Choice4(_Strict):
    format: Literal["choice4"] = "choice4"
    content: Choice4Content
    answer: Choice4Answer

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_blank(self.content.stem)
        if not _distinct(self.content.options):
            raise ValueError("options must be distinct")
        if self.answer.correct not in self.content.options:
            raise ValueError("the correct answer must be one of the options")
        return self


# --- cloze: type the missing word(s), with the base form as a hint ---


class ClozeContent(_Strict):
    stem: Text
    # E.g. the verb to put in the right form; None when the gap needs no hint.
    hint: Text | None = None


class ClozeAnswer(_Strict):
    accepted: Accepted
    explanation: Explanation


class Cloze(_Strict):
    format: Literal["cloze"] = "cloze"
    content: ClozeContent
    answer: ClozeAnswer

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_blank(self.content.stem)
        if not _distinct(self.answer.accepted):
            raise ValueError("accepted answers must be distinct")
        return self


# --- find_fix: spot the wrong part of a sentence, then correct it ---


class FindFixContent(_Strict):
    # The sentence in consecutive pieces, joined as they are (pieces carry their own
    # spaces and punctuation); the learner picks the piece that is wrong.
    segments: Annotated[tuple[Text, ...], Field(min_length=3, max_length=6)]

    @property
    def sentence(self) -> str:
        return "".join(self.segments)


class FindFixAnswer(_Strict):
    wrong_segment: int = Field(ge=0)
    # Replacements for the wrong piece.
    accepted: Accepted
    explanation: Explanation


class FindFix(_Strict):
    format: Literal["find_fix"] = "find_fix"
    content: FindFixContent
    answer: FindFixAnswer

    @model_validator(mode="after")
    def _check(self) -> Self:
        segments = self.content.segments
        if any(not s.strip() for s in segments):
            raise ValueError("segments must not be blank")
        if self.answer.wrong_segment >= len(segments):
            raise ValueError("wrong_segment is out of range")
        wrong = normalize(segments[self.answer.wrong_segment])
        if any(normalize(fix) == wrong for fix in self.answer.accepted):
            raise ValueError("a fix must differ from the wrong segment")
        if not _distinct(self.answer.accepted):
            raise ValueError("accepted answers must be distinct")
        return self


# --- open formats: the learner writes a sentence; the model grades it ---


class OpenAnswer(_Strict):
    accepted: Accepted
    explanation: Explanation


class TransformContent(_Strict):
    # What to do, e.g. "Rewrite in the passive voice."
    instruction: Text
    source: Text


class Transform(_Strict):
    format: Literal["transform"] = "transform"
    content: TransformContent
    answer: OpenAnswer

    @model_validator(mode="after")
    def _check(self) -> Self:
        source = normalize(self.content.source)
        if any(normalize(a) == source for a in self.answer.accepted):
            raise ValueError("an accepted answer must differ from the source")
        return self


class TranslateContent(_Strict):
    # The sentence in the learner's language (Chinese first).
    source: Text
    # Names the structure to use, e.g. "Use the present perfect."
    instruction: Text | None = None


class Translate(_Strict):
    format: Literal["translate"] = "translate"
    content: TranslateContent
    answer: OpenAnswer


class RewriteOwnContent(_Strict):
    instruction: Text
    # The learner's own sentence, from their mistake evidence.
    original: Text
    # The kc_evidence row it came from; set by the code, never by the model.
    evidence_id: int = Field(ge=1)


class RewriteOwn(_Strict):
    format: Literal["rewrite_own"] = "rewrite_own"
    content: RewriteOwnContent
    answer: OpenAnswer

    @model_validator(mode="after")
    def _check(self) -> Self:
        original = normalize(self.content.original)
        if any(normalize(a) == original for a in self.answer.accepted):
            raise ValueError("an accepted answer must differ from the original")
        return self


ExerciseBody = Annotated[
    Choice4 | Cloze | FindFix | Transform | Translate | RewriteOwn,
    Field(discriminator="format"),
]
_BODY: TypeAdapter[ExerciseBody] = TypeAdapter(ExerciseBody)


def parse_body(fmt: str, content: Any, answer: Any) -> ExerciseBody:
    """Validate an item's parts, e.g. as read back from the `exercises` columns."""
    return _BODY.validate_python({"format": fmt, "content": content, "answer": answer})


# --- the learner's answer ---


class ChoiceResponse(_Strict):
    choice: Text


class TextResponse(_Strict):
    text: Annotated[str, Field(min_length=1, max_length=1000)]


class FindFixResponse(_Strict):
    segment: int = Field(ge=0)
    fix: Text


Response = ChoiceResponse | TextResponse | FindFixResponse


@dataclass(frozen=True)
class FormatSpec:
    body: type[BaseModel]
    response: type[Response]
    grading: Grading
    # The observations one answer yields, in order. find_fix gives two: spotting the
    # error is recognition, writing the fix is production.
    evidence: tuple[Evidence, ...]


SPECS: dict[Format, FormatSpec] = {
    "choice4": FormatSpec(Choice4, ChoiceResponse, "code", ("recognition",)),
    "cloze": FormatSpec(Cloze, TextResponse, "code", ("recognition",)),
    "find_fix": FormatSpec(
        FindFix, FindFixResponse, "code_then_model", ("recognition", "production")
    ),
    "transform": FormatSpec(Transform, TextResponse, "model", ("production",)),
    "translate": FormatSpec(Translate, TextResponse, "model", ("production",)),
    "rewrite_own": FormatSpec(RewriteOwn, TextResponse, "model", ("production",)),
}


def parse_response(fmt: Format, data: Any) -> Response:
    """Validate a learner's answer against the shape its format expects."""
    return SPECS[fmt].response.model_validate(data)
