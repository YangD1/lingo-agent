"""Presets, default routes and per-tenant route resolution (ADR 0002 + ADR 0004)."""

import logging
import os
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
Section = Literal["llm", "embedding", "asr"]
SECTIONS: tuple[Section, ...] = ("llm", "embedding", "asr")
# Kinds whose SDK offers an embeddings API.
EMBEDDING_KINDS: frozenset[str] = frozenset({"openai", "openai_compatible"})
# Kinds that can serve OpenAI's /audio/transcriptions (OpenAI, Groq, speaches, ...).
ASR_KINDS: frozenset[str] = frozenset({"openai", "openai_compatible"})
# Tasks needing a capability that can't be inferred from a model's name (ADR 0008 §5):
# they run only on models configured for them explicitly - never on the section's
# default route nor on the connections' default chat models - because a model that
# can't see images would invent what they show.
CAPABILITY_TASKS: frozenset[tuple[str, str]] = frozenset({("llm", "vision")})


class PresetSpec(BaseModel):
    """A vendor template tenants create connections from."""

    model_config = ConfigDict(extra="forbid")

    kind: ProviderKind
    base_url: str
    # Environment variable that replaces `base_url` when set: the same local server is
    # reached at a different address from the compose backend than from one on the host.
    base_url_env: str | None = None
    label: str | None = None
    models: list[str] = []  # suggestions for the UI, not an allow-list

    @model_validator(mode="after")
    def _base_url_from_env(self) -> Self:
        if self.base_url_env and (value := os.environ.get(self.base_url_env, "").strip()):
            self.base_url = value
        return self


class RouteSpec(BaseModel):
    """A model chain for one task: primary model first, then fallbacks."""

    model_config = ConfigDict(extra="forbid")

    models: list[str]
    params: dict[str, Any] = {}
    # Refs from `models` the tenant switched off: kept in the chain, never called (ADR 0026).
    disabled: list[str] = []

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
            params = {k: v for k, v in value.items() if k not in ("models", "disabled")}
            return {
                "models": [models] if isinstance(models, str) else models,
                "params": params,
                "disabled": value.get("disabled", []),
            }
        return value

    @model_validator(mode="after")
    def _check_models(self) -> Self:
        if not self.models:
            raise ValueError("a route needs at least one model")
        for ref in self.models:
            connection, _, model = ref.partition(":")
            if not connection or not model:
                raise ValueError(f"model ref {ref!r} must look like '<connection>:<model>'")
        for ref in self.disabled:
            if ref not in self.models:
                raise ValueError(f"disabled model {ref!r} is not in the route")
        return self


class SectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: RouteSpec
    routes: dict[str, RouteSpec] = {}
    # Call params by task, whatever its route: over `defaults`, under the connection's
    # and the route's own params. For tasks that need them without a route of their
    # own, e.g. a longer timeout for slow structured calls (task 49.3).
    task_params: dict[str, dict[str, Any]] = {}

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
    asr: SectionSpec | None = None

    @model_validator(mode="after")
    def _check_refs(self) -> Self:
        for section_name in SECTIONS:
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
                if section_name == "asr":
                    check_asr_route(route, lambda n: self.presets[n].kind)
        return self

    def section(self, name: Section) -> SectionSpec | None:
        spec: SectionSpec | None = getattr(self, name)
        return spec


def check_embedding_route(route: RouteSpec, kind_of: Any) -> None:
    # Vectors from different embedding models live in different spaces, so falling
    # back would silently corrupt similarity search (ADR 0002 §2.5).
    if len(route.models) != 1:
        raise ValueError("embedding routes take exactly one model (no fallback)")
    name = route.models[0].partition(":")[0]
    if kind_of(name) not in EMBEDDING_KINDS:
        raise ValueError(f"connection {name!r} does not support embeddings")


def check_asr_route(route: RouteSpec, kind_of: Any) -> None:
    for ref in route.models:
        name = ref.partition(":")[0]
        if kind_of(name) not in ASR_KINDS:
            raise ValueError(f"connection {name!r} has no speech-to-text API")


@dataclass(frozen=True)
class ConnectionSpec:
    """A tenant connection with its key already decrypted. Lives in memory only."""

    name: str
    kind: ProviderKind
    base_url: str
    api_key: SecretStr | None
    params: dict[str, Any] = field(default_factory=dict)
    # The tenant's pick for chat; used when no route matches (ADR 0007 §3).
    default_model: str | None = None


@dataclass(frozen=True)
class TenantProviderContext:
    """Everything needed to build a tenant's models; loaded once per request."""

    tenant_id: uuid.UUID
    connections: Mapping[str, ConnectionSpec]  # in creation order (the auto fallback order)
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
        if section == "asr":  # optional: deployments may leave speech out entirely
            raise NoModelConfiguredError(section, task, [])
        raise ProviderConfigError(f"no '{section}' section in providers config")
    if (section, task) in CAPABILITY_TASKS and task not in spec.routes:
        raise NoModelConfiguredError(section, task, [])
    return spec.route_for(task)


# Where a task's effective model chain came from (ADR 0007 §3).
RouteSource = Literal["override", "default", "auto"]


def resolve_route(
    config: ProvidersConfig, ctx: TenantProviderContext, section: Section, task: str
) -> list[ResolvedModel]:
    """The task's model chain, limited to connections this tenant has (and enabled)."""
    return resolve_route_with_source(config, ctx, section, task)[0]


def resolve_route_with_source(
    config: ProvidersConfig, ctx: TenantProviderContext, section: Section, task: str
) -> tuple[list[ResolvedModel], RouteSource]:
    """Tenant override > YAML route; if neither matches a connection, each connection's
    default model in creation order (llm only, and not speech-to-text models).

    Models switched off in the route are skipped, and a route with any of them never falls
    back to default models: the tenant chose what this task may use (ADR 0026)."""
    route = route_for(config, ctx, section, task)
    source: RouteSource = "override" if (section, task) in ctx.routes else "default"
    resolved: list[ResolvedModel] = []
    for ref in route.models:
        if ref in route.disabled:
            continue
        name, _, model = ref.partition(":")
        conn = ctx.connections.get(name)
        if conn is None:
            logger.debug(
                "%s.%s: tenant %s has no connection %r", section, task, ctx.tenant_id, name
            )
            continue
        resolved.append(_resolved(config, conn, model, route, section, task))
    if not resolved and route.disabled:
        raise NoModelConfiguredError(section, task, route.models, disabled=True)
    if not resolved and section == "llm" and (section, task) not in CAPABILITY_TASKS:
        # Imported here: model_catalog imports this module.
        from app.providers.model_catalog import looks_like_speech_to_text

        source = "auto"
        # A speech-only connection's default model can't chat, so it is left out.
        resolved = [
            _resolved(config, conn, conn.default_model, route, section, task)
            for conn in ctx.connections.values()
            if conn.default_model and not looks_like_speech_to_text(conn.default_model)
        ]
    if not resolved:
        raise NoModelConfiguredError(section, task, route.models)
    return resolved, source


def _resolved(
    config: ProvidersConfig,
    conn: ConnectionSpec,
    model: str,
    route: RouteSpec,
    section: Section,
    task: str,
) -> ResolvedModel:
    spec = config.section(section)
    by_task = spec.task_params.get(task, {}) if spec is not None else {}
    return ResolvedModel(
        connection=conn.name,
        kind=conn.kind,
        model=model,
        base_url=conn.base_url,
        api_key=conn.api_key,
        params={**config.defaults, **by_task, **conn.params, **route.params},
    )
