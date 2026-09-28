import pytest
from pydantic import ValidationError

from app.settings import DEFAULT_JWT_SECRET, REPO_ROOT, Settings


def test_prod_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, app_env="prod", jwt_secret=DEFAULT_JWT_SECRET)


def test_prod_rejects_empty_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, app_env="prod", jwt_secret="")


def test_prod_accepts_custom_jwt_secret() -> None:
    settings = Settings(_env_file=None, app_env="prod", jwt_secret="x" * 32)
    assert settings.app_env == "prod"


def test_dev_allows_default_jwt_secret() -> None:
    settings = Settings(_env_file=None, app_env="dev", jwt_secret=DEFAULT_JWT_SECRET)
    assert settings.jwt_secret == DEFAULT_JWT_SECRET


def test_relative_providers_config_resolves_against_repo_root() -> None:
    settings = Settings(_env_file=None, providers_config="config/providers.dev.yaml")
    assert settings.providers_config_path == REPO_ROOT / "config/providers.dev.yaml"


def test_prod_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(_env_file=None, app_env="prod", jwt_secret="x" * 31)
