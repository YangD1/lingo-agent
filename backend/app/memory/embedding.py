"""Embeddings for memory retrieval: optional, from the tenant's own model (ADR 0009 §2)."""

import logging
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

from app.providers.config import TenantProviderContext, resolve_route
from app.providers.embedding import get_embeddings
from app.providers.errors import NoModelConfiguredError, ProviderConfigError
from app.providers.llm import get_providers_config

logger = logging.getLogger(__name__)

EMBEDDING_TASK = "memory"


@dataclass(frozen=True)
class MemoryEmbedder:
    # "<connection>:<model>": vectors are only compared with ones from the same model.
    model_id: str
    embeddings: Embeddings

    async def embed(self, text: str) -> list[float] | None:
        """None if the vendor call fails: memory works without vectors, just less well."""
        try:
            return await self.embeddings.aembed_query(text)
        except Exception:
            logger.warning("memory embedding with %s failed", self.model_id, exc_info=True)
            return None


def memory_embedder(ctx: TenantProviderContext) -> MemoryEmbedder | None:
    """None when the tenant has no embedding model, or the deployment no `embedding`
    section."""
    try:
        (resolved,) = resolve_route(get_providers_config(), ctx, "embedding", EMBEDDING_TASK)
        embeddings = get_embeddings(ctx, EMBEDDING_TASK)
    except (NoModelConfiguredError, ProviderConfigError):
        return None
    return MemoryEmbedder(f"{resolved.connection}:{resolved.model}", embeddings)
