"""Which language the tutor mainly talks in (ADR 0017 §1)."""

from typing import Literal

type ChatLanguage = Literal["zh", "en"]

# Levels at which the tutor talks mainly in Chinese unless the learner chose otherwise.
_CHINESE_LEVELS = frozenset({"A1", "A2"})


def chat_language(chosen: str | None, cefr_level: str | None) -> ChatLanguage:
    """The learner's own choice; otherwise Chinese for beginners and learners whose
    level isn't known yet (Q24e), English from B1 up."""
    if chosen == "zh":
        return "zh"
    if chosen == "en":
        return "en"
    if cefr_level is None or cefr_level in _CHINESE_LEVELS:
        return "zh"
    return "en"


# Without the learner's profile: as for a learner whose level isn't known.
DEFAULT_CHAT_LANGUAGE: ChatLanguage = chat_language(None, None)
