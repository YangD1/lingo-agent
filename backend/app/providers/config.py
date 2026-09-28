"""Presets, default routes and per-tenant route resolution (ADR 0002 + ADR 0004)."""

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, model_validator

from app.providers.errors import NoModelConfiguredError, ProviderConfigError

logger = logging.getLogger(__name__)

ProviderKind = Literal["deepseek", "anthropic", "openai", "openai_compatible"]
Section = Literal["llm", "embedding"]
# Kinds whose SDK offers an embeddings API.
EMBEDDING_KINDS: frozenset[str] = frozenset({"openai", "openai_compatible"})


class PresetSpec(BaseModel):
    """A vendor template tenants create connections from."""

    model_config = ConfigDict(extra="forbid")

    kind: ProviderKind
    base_url: str
    label: str | None = None
    models: list[str] = []  # suggestions for the UI, not an allow-list


class RouteSpec(BaseModel):
    """A model chain for one task: primary model first, then fallbacks."""

    model_config = ConfigDict(extra="forbid")

    models: list[str]
    params: dict[str, Any] = {}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        # Accept "c:m", ["c:m", ...] or {"models": [...], <call params>...}.
        if isinstance(value, str):
            return {"models": [value]}
        if isinstance(value, list):
            return {"models": value}
        if isinstance(value, dict) and "params" not in value:
            models = value.get("models")
            params = {k: v for k, v in value.items() if k != "models"}
            return {"models": [models] if isinstance(models, str) else models, "params": params}
        return value

    @model_validator(mode="after")
    def _check_models(self) -> Self:
        if not self.models:
            raise ValueError("a route needs at least one model")
        for ref in self.models:
            connection, _, model = ref.partition(":")
            if not connection or not model:
                raise ValueError(f"model ref {ref!r} must look like '<connection>:<model>'")
        return self


class SectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: RouteSpec
    routes: dict[str, RouteSpec] = {}

    def route_for(self, task: str) -> RouteSpec:
        return self.routes.get(task, self.default)

    def all_routes(self) -> dict[str, RouteSpec]:
        return {"default": self.default, **self.routes}


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presets: dict[str, PresetSpec]
    defaults: dict[str, Any] = {}
    llm: SectionSpec
    embedding: SectionSpec | None = None

    @model_validator(mode="after")
    def _check_refs(self) -> Self:
        for section_name in ("llm", "embedding"):
            section: SectionSpec | None = getattr(self, section_name)
            if section is None:
                continue
            for task, route in section.all_routes().items():
                for ref in route.models:
                    name = ref.partition(":")[0]
                    # Default routes target connections named after presets.
                    if name not in self.presets:
                        raise ValueError(
                            f"{section_name}.{task}: unknown preset {name!r} in {ref!r}"
                        )
                if section_name == "embedding":
                    check_embedding_route(route, lambda n: self.presets[n].kind)
        return self

    def section(self, name: Section) -> SectionSpec | None:
        return self.llm if name == "llm" else self.embedding


def check_embedding_route(route: RouteSpec, kind_of: Any) -> None:
    # Vectors from different embedding models live in different spaces, so falling
    # back would silently corrupt similarity search (ADR 0002 §2.5).
    if len(route.models) != 1:
        raise ValueError("embedding routes take exactly one model (no fallback)")
    name = route.models[0].partition(":")[0]
    if kind_of(name) not in EMBEDDING_KINDS:
        raise ValueError(f"connection {name!r} does not support embeddings")


@dataclass(frozen=True)
class ConnectionSpec:
    """A tenant connection with its key already decrypted. Lives in memory only."""

    name: str
    kind: ProviderKind
    base_url: str
    api_key: SecretStr | None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TenantProviderContext:
    """Everything needed to build a tenant's models; loaded once per request."""

    tenant_id: uuid.UUID
    connections: Mapping[str, ConnectionSpec]
    routes: Mapping[tuple[str, str], RouteSpec]  # (section, task) -> tenant override
    # Changes whenever the tenant's connections or routes change; part of cache keys.
    version: str


@dataclass(frozen=True)
class ResolvedModel:
    connection: str
    kind: ProviderKind
    model: str
    base_url: str
    api_key: SecretStr | None
    params: dict[str, Any] = field(default_factory=dict)


def load_providers_config(path: Path) -> ProvidersConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProviderConfigError(f"providers config not found: {path}") from exc
    try:
        return ProvidersConfig.model_validate(raw)
    except ValidationError as exc:
        raise ProviderConfigError(f"invalid providers config {path}:\n{exc}") from exc


def route_for(
    config: ProvidersConfig, ctx: TenantProviderContext, section: Section, task: str
) -> RouteSpec:
    """Tenant override > YAML route for the task > YAML default route."""
    override = ctx.routes.get((section, task))
    if override is not None:
        return override
    spec = config.section(section)
    if spec is None:
        raise ProviderConfigError(f"no '{section}' section in providers config")
    return spec.route_for(task)


def resolve_route(
    config: ProvidersConfig, ctx: TenantProviderContext, section: Section, task: str
) -> list[ResolvedModel]:
    """The task's model chain, limited to connections this tenant has (and enabled)."""
    route = route_for(config, ctx, section, task)
    resolved: list[ResolvedModel] = []
    for ref in route.models:
        name, _, model = ref.partition(":")
        conn = ctx.connections.get(name)
        if conn is None:
            logger.debug(
                "%s.%s: tenant %s has no connection %r", section, task, ctx.tenant_id, name
            )
            continue
        resolved.append(
            ResolvedModel(
                connection=name,
                kind=conn.kind,
                model=model,
                base_url=conn.base_url,
                api_key=conn.api_key,
                params={**config.defaults, **conn.params, **route.params},
            )
        )
    if not resolved:
        raise NoModelConfiguredError(section, task, route.models)
    return resolved
