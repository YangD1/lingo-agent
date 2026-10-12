"""What a learner may pick for their tutor (ADR 0032 §2): the models and voices of the
chains that serve them now, whether their own or their main account's.

Pure: computed from the providers config and the learner's provider context.
"""

from dataclasses import dataclass, field

from app.providers.config import (
    ProvidersConfig,
    ResolvedModel,
    Section,
    TenantProviderContext,
    context_for,
    resolve_route,
    route_for,
)
from app.providers.errors import NoModelConfiguredError, QuotaExhaustedError
from app.providers.tts import LANGUAGES, Language, default_voice
from app.providers.tts_voices import VoiceOption, voice_options

# The chains a learner picks in (ADR 0032 §1): every conversation call resolves `chat`.
CHAT: tuple[Section, str] = ("llm", "chat")
READ_ALOUD: tuple[Section, str] = ("tts", "default")
REALTIME: tuple[Section, str] = ("realtime", "default")


@dataclass(frozen=True)
class Chain:
    """One chain's usable models, in route order."""

    models: list[ResolvedModel] = field(default_factory=list)
    # The main account's name when its models serve this chain.
    provided_by: str | None = None
    # The main account's model would serve it, but the learner's quota is used up.
    quota_exhausted: bool = False

    @property
    def refs(self) -> list[str]:
        return [ref(m) for m in self.models]


@dataclass(frozen=True)
class TutorOptions:
    chat: Chain
    read_aloud: Chain
    realtime: Chain

    @property
    def tts_model(self) -> ResolvedModel | None:
        """The read-aloud model voices are picked for: the first in the chain."""
        return self.read_aloud.models[0] if self.read_aloud.models else None

    def tts_voices(self) -> tuple[VoiceOption, ...]:
        model = self.tts_model
        return voice_options(model) if model else ()

    def tts_default_voices(
        self, config: ProvidersConfig, ctx: TenantProviderContext
    ) -> dict[Language, str | None]:
        """What the first read-aloud model reads each language with now: the route's
        voice, else the model's own default."""
        model = self.tts_model
        if model is None:
            return {}
        section, task = READ_ALOUD
        voices = route_for(config, context_for(config, ctx, section, task), section, task)
        chosen = (voices.params.get("voices") or {}).get(ref(model), {})
        return {lang: chosen.get(lang) or default_voice(model, lang) for lang in LANGUAGES}

    def realtime_model(self, model_ref: str) -> ResolvedModel | None:
        return next((m for m in self.realtime.models if ref(m) == model_ref), None)


def ref(model: ResolvedModel) -> str:
    return f"{model.connection}:{model.model}"


def chain(
    config: ProvidersConfig, ctx: TenantProviderContext, section: Section, task: str
) -> Chain:
    try:
        resolved = resolve_route(config, ctx, section, task)
    except QuotaExhaustedError:
        name = ctx.sponsor.name if ctx.sponsor else None
        return Chain(provided_by=name, quota_exhausted=True)
    except NoModelConfiguredError:
        return Chain()
    sponsored = resolved[0].billed_tenant_id is not None and ctx.sponsor is not None
    return Chain(resolved, ctx.sponsor.name if sponsored and ctx.sponsor else None)


def tutor_options(config: ProvidersConfig, ctx: TenantProviderContext) -> TutorOptions:
    return TutorOptions(
        chat=chain(config, ctx, *CHAT),
        read_aloud=chain(config, ctx, *READ_ALOUD),
        realtime=chain(config, ctx, *REALTIME),
    )
