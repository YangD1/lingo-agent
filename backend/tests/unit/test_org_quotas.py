import pytest
from pydantic import ValidationError

from app.db.models import ROUTE_SECTIONS
from app.org.quotas import (
    CAPABILITIES,
    CAPABILITY_OF_SECTION,
    DEFAULT_QUOTAS,
    SECTIONS,
    UNITS,
    Limit,
    Quotas,
)


def test_every_route_section_belongs_to_one_capability() -> None:
    assert sorted(CAPABILITY_OF_SECTION) == sorted(ROUTE_SECTIONS)
    assert set(SECTIONS) == set(CAPABILITIES) == set(UNITS)


def test_default_template_matches_q65e() -> None:
    assert DEFAULT_QUOTAS.text == Limit(daily=200_000, monthly=3_000_000)
    assert DEFAULT_QUOTAS.tts == Limit(daily=20_000)
    assert DEFAULT_QUOTAS.asr == Limit(daily=30)
    assert DEFAULT_QUOTAS.pronunciation == Limit(daily=10)
    assert DEFAULT_QUOTAS.realtime == Limit(daily=30)


def test_missing_capabilities_have_no_cap() -> None:
    quotas = Quotas.model_validate({"text": {"daily": 0}})
    assert quotas.limit("text") == Limit(daily=0, monthly=None)
    assert quotas.limit("tts") == Limit()


def test_dump_round_trips() -> None:
    assert Quotas.model_validate(DEFAULT_QUOTAS.model_dump()) == DEFAULT_QUOTAS


@pytest.mark.parametrize(
    "data",
    [
        {"text": {"daily": -1}},
        {"text": {"weekly": 5}},
        {"video": {"daily": 5}},
    ],
)
def test_rejects_bad_quotas(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Quotas.model_validate(data)
