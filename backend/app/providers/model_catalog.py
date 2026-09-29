"""Model discovery: which models a tenant's connection can serve (ADR 0007 §1).

Vendors expose a free "list models" endpoint that also proves the key works:
- OpenAI and everything OpenAI-compatible (DeepSeek, DashScope, Ollama, relays):
  `GET {base_url}/models`, Bearer auth, `{"data": [{"id": ...}]}`.
- Anthropic: `GET {base_url}/v1/models`, `x-api-key` auth, paginated with
  `has_more` / `last_id`.

Categories come from the model id alone, so they are a best-effort hint for the UI:
a misfiled model only means one extra option in a dropdown.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx2
from pydantic import SecretStr

from app.providers.config import ProviderKind

ModelCategory = Literal["chat", "embedding", "other"]

ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_PAGE_SIZE = 1000
_MAX_PAGES = 10

_EMBEDDING = re.compile(r"embed|^bge-|^e5-|^gte-", re.IGNORECASE)
# Speech, images, moderation, reranking, realtime audio and legacy completion models, plus
# what a local speaches server lists besides whisper (voice activity detection, TTS voices).
_OTHER = re.compile(
    r"whisper|tts|transcri|speech|audio|realtime|dall-e|image|sora|moderation|rerank"
    r"|silero|kokoro|piper|^(babbage|davinci)",
    re.IGNORECASE,
)


# Speech-to-text models, whose connection test sends audio instead of a chat message.
_SPEECH_TO_TEXT = re.compile(r"whisper|transcri|sensevoice|paraformer", re.IGNORECASE)


@dataclass(frozen=True)
class DiscoveredModel:
    id: str
    category: ModelCategory


class ModelListError(Exception):
    """The vendor refused or could not be reached; the message is safe to show the tenant."""


def categorize(model_id: str) -> ModelCategory:
    if _EMBEDDING.search(model_id):
        return "embedding"
    if _OTHER.search(model_id):
        return "other"
    return "chat"


def looks_like_speech_to_text(model_id: str) -> bool:
    return _SPEECH_TO_TEXT.search(model_id) is not None


async def fetch_models(
    kind: ProviderKind,
    base_url: str,
    api_key: SecretStr | None,
    *,
    client: httpx2.AsyncClient,
) -> list[DiscoveredModel]:
    """Sorted by id, without duplicates. `client` must be the SSRF-guarded one."""
    if kind == "anthropic":
        ids = await _anthropic_ids(base_url, api_key, client)
    else:
        headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"} if api_key else {}
        body = await _get_json(client, f"{base_url}/models", headers, params=None)
        ids = _ids(body)
    return [DiscoveredModel(id=i, category=categorize(i)) for i in sorted(set(ids))]


async def _anthropic_ids(
    base_url: str, api_key: SecretStr | None, client: httpx2.AsyncClient
) -> list[str]:
    headers = {"anthropic-version": ANTHROPIC_VERSION}
    if api_key is not None:
        headers["x-api-key"] = api_key.get_secret_value()
    ids: list[str] = []
    params: dict[str, Any] = {"limit": _ANTHROPIC_PAGE_SIZE}
    for _ in range(_MAX_PAGES):
        body = await _get_json(client, f"{base_url}/v1/models", headers, params=params)
        ids += _ids(body)
        if not body.get("has_more") or not body.get("last_id"):
            break
        params = {"limit": _ANTHROPIC_PAGE_SIZE, "after_id": body["last_id"]}
    return ids


async def _get_json(
    client: httpx2.AsyncClient, url: str, headers: dict[str, str], params: dict[str, Any] | None
) -> dict[str, Any]:
    try:
        response = await client.get(url, headers=headers, params=params)
    except httpx2.HTTPError as exc:  # includes SSRF refusals (ForbiddenDestinationError)
        raise ModelListError(f"{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise ModelListError(f"HTTP {response.status_code}: {_vendor_message(response)}")
    try:
        body = response.json()
    except ValueError as exc:
        raise ModelListError("the endpoint did not return JSON; check the base URL") from exc
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ModelListError("unexpected response shape; check the base URL")
    return body


def _ids(body: dict[str, Any]) -> list[str]:
    return [m["id"] for m in body["data"] if isinstance(m, dict) and isinstance(m.get("id"), str)]


def _vendor_message(response: httpx2.Response) -> str:
    """The vendor's own error text (e.g. "invalid api key"), trimmed."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200] or response.reason_phrase
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return str(error["message"])[:200]
    if isinstance(error, str):
        return error[:200]
    return str(body)[:200]
