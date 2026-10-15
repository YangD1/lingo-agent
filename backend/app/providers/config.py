"""Presets, default routes and per-tenant route resolution (ADR 0002 + ADR 0004)."""

import logging
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, model_validator

from app.providers.errors import (
    NoModelConfiguredError,
    ProviderConfigError,
    QuotaExhaustedError,
)

logger = logging.getLogger(__name__)

ProviderKind = Literal[
    "deepseek", "anthropic", "openai", "openai_compatible", "azure_speech", "gemini"
]
Section = Literal["llm", "embedding", "asr", "tts", "pronunciation", "realtime"]
SECTIONS: tuple[Section, ...] = ("llm", "embedding", "asr", "tts", "pronunciation", "realtime")
# Speech-only vendors: they serve no chat, embeddings or transcription API here. Azure
# reads aloud and scores pronunciation (ADR 0028 §2); Gemini only takes realtime voice
# calls (ADR 0030 §2, Q61j): its chat API is not wired up.
SPEECH_ONLY_KINDS: frozenset[str] = frozenset({"azure_speech", "gemini"})
# Kinds whose SDK offers an embeddings API.
EMBEDDING_KINDS: frozenset[str] = frozenset({"openai", "openai_compatible"})
# Kinds that can serve OpenAI's /audio/transcriptions (OpenAI, Groq, speaches, ...).
ASR_KINDS: frozenset[str] = frozenset({"openai", "openai_compatible"})
# Kinds that can read text aloud: OpenAI's /audio/speech (OpenAI, SiliconFlow, speaches)
# or Azure's text-to-speech REST API (ADR 0028 §2).
TTS_KINDS: frozenset[str] = frozenset({"openai", "openai_compatible", "azure_speech"})
# Kinds that score pronunciation against a reference text: Azure only for now (ADR 0028 §5).
PRONUNCIATION_KINDS: frozenset[str] = frozenset({"azure_speech"})
# Kinds that take realtime voice calls over a WebSocket: the OpenAI Realtime protocol
# (OpenAI, Qwen-Omni, StepFun) or Gemini Live (ADR 0030 §2).
REALTIME_KINDS: frozenset[str] = frozenset({"openai", "openai_compatible", "gemini"})
# Connection params only realtime calls read (Q60c): never passed to a chat or
# embeddings SDK, whose constructors take every other param.
REALTIME_PARAMS: frozenset[str] = frozenset({"realtime_url", "realtime_dialect"})
# Connection params only speech endpoints read, never passed to an SDK either: Bailian's
# qwen-audio reads aloud on the workspace's own host (task 64.2a).
SPEECH_URL_PARAMS: frozenset[str] = frozenset({"tts_url"})
# Every param that belongs on a connection and must never reach an SDK constructor.
NON_SDK_PARAMS: frozenset[str] = REALTIME_PARAMS | SPEECH_URL_PARAMS
# Sections a deployment may leave out entirely.
OPTIONAL_SPEECH_SECTIONS: frozenset[str] = frozenset({"asr", "tts", "pronunciation", "realtime"})
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
    tts: SectionSpec | None = None
    pronunciation: SectionSpec | None = None
    realtime: SectionSpec | None = None

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
                if section_name == "tts":
                    check_tts_route(route, lambda n: self.presets[n].kind)
                if section_name == "pronunciation":
                    check_pronunciation_route(route, lambda n: self.presets[n].kind)
                if section_name == "realtime":
                    check_realtime_route(route, lambda n: self.presets[n].kind)
                if section_name == "llm":
                    check_llm_route(route, lambda n: self.presets[n].kind)
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


def check_llm_route(route: RouteSpec, kind_of: Any) -> None:
    for ref in route.models:
        name = ref.partition(":")[0]
        if kind_of(name) in SPEECH_ONLY_KINDS:
            raise ValueError(f"connection {name!r} is speech-only and cannot chat")


def check_tts_route(route: RouteSpec, kind_of: Any) -> None:
    for ref in route.models:
        name = ref.partition(":")[0]
        if kind_of(name) not in TTS_KINDS:
            raise ValueError(f"connection {name!r} cannot read text aloud")


def check_pronunciation_route(route: RouteSpec, kind_of: Any) -> None:
    for ref in route.models:
        name = ref.partition(":")[0]
        if kind_of(name) not in PRONUNCIATION_KINDS:
            raise ValueError(f"connection {name!r} cannot assess pronunciation")


def check_realtime_route(route: RouteSpec, kind_of: Any) -> None:
    for ref in route.models:
        name = ref.partition(":")[0]
        if kind_of(name) not in REALTIME_KINDS:
            raise ValueError(f"connection {name!r} has no realtime voice API")


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
    # Changes whenever the tenant's connections or routes change, or its main account's;
    # part of cache keys.
    version: str
    sponsor: "Sponsor | None" = None
    # The learner's own tutor (ADR 0032); never set on a main account's lent context.
    tutor: "TutorPick | None" = None


@dataclass(frozen=True)
class TutorPick:
    """What the learner picked for the tutor talking to them (ADR 0032 §1, §3).

    Model refs name a model of whichever chain serves the learner; a pick no longer in
    that chain is ignored. Voices apply only to the model they were picked for.
    """

    name: str | None = None
    chat_model: str | None = None
    tts_model: str | None = None
    voices: Mapping[str, str] = field(default_factory=dict)
    realtime_model: str | None = None
    realtime_voice: str | None = None
    # Not a model pick, but the tutor's own setting its prompt follows (ADR 0045 §3).
    workspace_auto_open: bool = True


@dataclass(frozen=True)
class Sponsor:
    """The main account lending this tenant its connections (ADR 0031 §5)."""

    # The main account's own connections and routes (never its own main account's).
    ctx: TenantProviderContext
    name: str
    # Sections the member may not use the main account's models for right now: the
    # capability's quota is used up today or this month, or set to 0.
    exhausted: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ResolvedModel:
    connection: str
    kind: ProviderKind
    model: str
    base_url: str
    api_key: SecretStr | None
    params: dict[str, Any] = field(default_factory=dict)
    # Params whose value is only the deployment's `defaults` (no task, connection or route
    # set it): a model that needs more, e.g. a slower timeout, may go over them (Q64t).
    deployment_defaults: frozenset[str] = frozenset()
    # The main account paying for this model, when a member uses its connection (ADR
    # 0031 §6); None: the tenant itself.
    billed_tenant_id: uuid.UUID | None = None


def sdk_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """A model's params for an SDK constructor: without the ones only realtime or a
    speech endpoint reads."""
    return {k: v for k, v in params.items() if k not in NON_SDK_PARAMS}


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
        if section in OPTIONAL_SPEECH_SECTIONS:  # deployments may leave speech out entirely
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
    """The tenant's own chain when it has one, else its main account's (ADR 0031 §5).

    Never a mix: a member's own models don't fall back to the main account's. Models the
    member switched off stay off. Raises QuotaExhaustedError when only the main account
    has a model and the member's quota for it is used up.
    """
    try:
        resolved, source = _resolve_own(config, ctx, section, task)
    except NoModelConfiguredError as exc:
        sponsor = ctx.sponsor
        if sponsor is None or exc.code == "models_disabled":
            raise
        try:
            resolved, source = _resolve_own(config, sponsor.ctx, section, task)
        except NoModelConfiguredError:
            raise exc from None
        if section in sponsor.exhausted:
            raise QuotaExhaustedError(section, task) from None
        billed = sponsor.ctx.tenant_id
        resolved = [replace(r, billed_tenant_id=billed) for r in resolved]
    return _picked_first(ctx.tutor, section, task, resolved), source


# The chains a learner may pick a model in, and which pick (ADR 0032 §1).
_PICKS: dict[tuple[str, str], str] = {
    ("llm", "chat"): "chat_model",
    ("realtime", "default"): "realtime_model",
}


def _picked_first(
    tutor: TutorPick | None, section: Section, task: str, resolved: list[ResolvedModel]
) -> list[ResolvedModel]:
    """The learner's pick moved to the front, the rest kept as fallbacks in order; a pick
    not in the chain (any more) changes nothing (ADR 0032 §3)."""
    pick = _PICKS.get((section, task))
    picked = getattr(tutor, pick) if tutor is not None and pick else None
    if picked is None:
        return resolved
    first = [r for r in resolved if f"{r.connection}:{r.model}" == picked]
    return first + [r for r in resolved if r not in first] if first else resolved


def own_only(ctx: TenantProviderContext) -> TenantProviderContext:
    """The tenant's own connections, without its main account's: for work a member may
    not spend the main account's quota on, like pinning word audio (ADR 0031 §7)."""
    return replace(ctx, sponsor=None) if ctx.sponsor is not None else ctx


def context_for(
    config: ProvidersConfig, ctx: TenantProviderContext, section: Section, task: str
) -> TenantProviderContext:
    """Whose connections and routes serve `task`: the tenant's, or its main account's."""
    if ctx.sponsor is not None:
        try:
            if resolve_route(config, ctx, section, task)[0].billed_tenant_id is not None:
                return ctx.sponsor.ctx
        except NoModelConfiguredError:
            pass
    return ctx


def _resolve_own(
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
            if conn.default_model
            and conn.kind not in SPEECH_ONLY_KINDS
            and not looks_like_speech_to_text(conn.default_model)
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
        deployment_defaults=frozenset(config.defaults) - {*by_task, *conn.params, *route.params},
    )
