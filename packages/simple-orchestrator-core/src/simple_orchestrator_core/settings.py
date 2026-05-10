from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    PyprojectTomlConfigSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)
from ulid import ULID

from .validators import MAX_DESCRIPTION_LENGTH, ValidULID

_TOML_FILE_ENV = "ORCHESTRATOR_TOML_FILE"


def get_base_dir() -> Path:
    try:
        return Path.home() / "simple-orchestrator"
    except RuntimeError, OSError:
        return Path(tempfile.gettempdir()) / "simple-orchestrator"


class _OrchestratorSettingsBase(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCHESTRATOR_",
        env_file=".env",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
        pyproject_toml_table_header=("tool", "simple-orchestrator"),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
        ]

        toml_path = Path(os.environ.get(_TOML_FILE_ENV, "orchestrator.toml"))
        if toml_path.exists():
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=toml_path))

        pyproject_path = Path("pyproject.toml")
        if pyproject_path.exists():
            sources.append(PyprojectTomlConfigSettingsSource(settings_cls, toml_file=pyproject_path))

        return tuple(sources)


class WebApiSettings(_OrchestratorSettingsBase):
    db_path: str = str(get_base_dir() / "orchestrator.db")
    logs_dir: Path = get_base_dir() / "logs"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    webapi_host: str = "127.0.0.1"
    webapi_port: int = 8765
    api_key: str = "change-me"

    task_timeout_minutes: float = Field(default=30.0, gt=0)
    max_completed_items: int = Field(default=15, ge=1)
    max_completed_age_days: int = Field(default=7, ge=1)
    heartbeat_ttl_seconds: float = Field(default=30.0, gt=0)


class WorkerSettings(_OrchestratorSettingsBase):
    logs_dir: Path = get_base_dir() / "logs"
    git_cache_dir: Path = get_base_dir() / "git"
    db_path: str = str(get_base_dir() / "orchestrator.db")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    api_url: str = "http://127.0.0.1:8765"
    api_key: str = "change-me"

    worker_id: ValidULID = Field(default_factory=lambda: str(ULID()))
    worker_name: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)

    max_active_sessions: int = Field(default=4, ge=1)
    poll_interval_seconds: float = Field(default=1.0, gt=0)
    default_task_timeout_minutes: float = Field(default=30.0, gt=0)
    heartbeat_interval_seconds: float = Field(default=10.0, gt=0)
    always_open_pr: bool = True


class TuiSettings(_OrchestratorSettingsBase):
    logs_dir: Path = get_base_dir() / "logs"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    db_path: str = str(get_base_dir() / "orchestrator.db")
    api_url: str = "http://127.0.0.1:8765"
    api_key: str = "change-me"

    standalone: bool = True


class FrontendSettings(_OrchestratorSettingsBase):
    logs_dir: Path = get_base_dir() / "logs"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    api_url: str = "http://127.0.0.1:8765"
    api_key: str = "change-me"

    frontend_host: str = "127.0.0.1"
    frontend_port: int = 8766
