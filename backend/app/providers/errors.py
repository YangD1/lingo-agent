class ProviderConfigError(ValueError):
    """providers.*.yaml, a tenant connection or a tenant route is invalid."""


class NoModelConfiguredError(Exception):
    """The tenant has no usable connection for any model in the task's route."""

    def __init__(self, section: str, task: str, refs: list[str], *, disabled: bool = False) -> None:
        self.section = section
        self.task = task
        # The codes the UI keys its guidance on; vision and speech are set up separately.
        # Models the tenant switched off are a choice, not missing setup (ADR 0026).
        if disabled:
            self.code = "models_disabled"
        elif section == "asr":
            self.code = "no_asr_model"
        elif section == "tts":
            self.code = "no_tts_model"
        elif section == "pronunciation":
            self.code = "no_pronunciation_model"
        elif section == "realtime":
            self.code = "no_realtime_model"
        elif (section, task) == ("llm", "vision"):
            self.code = "no_vision_model"
        else:
            self.code = f"no_{section}_configured"
        super().__init__(f"{section}.{task}: none of {refs} is configured for this tenant")


QUOTA_MESSAGE = "Your quota from your main account is used up for now."


class QuotaExhaustedError(NoModelConfiguredError):
    """Only the main account has a model for this task, and the member's quota for it is
    used up or 0 (ADR 0031 §6): to callers, like having no model."""

    def __init__(self, section: str, task: str) -> None:
        super().__init__(section, task, [])
        self.code = "quota_exhausted"
        self.args = (f"{section}.{task}: the member's quota is used up",)
