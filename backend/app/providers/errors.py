class ProviderConfigError(ValueError):
    """providers.*.yaml, a tenant connection or a tenant route is invalid."""


class NoModelConfiguredError(Exception):
    """The tenant has no usable connection for any model in the task's route."""

    def __init__(self, section: str, task: str, refs: list[str]) -> None:
        self.section = section
        self.task = task
        self.code = f"no_{section}_configured"
        super().__init__(f"{section}.{task}: none of {refs} is configured for this tenant")
