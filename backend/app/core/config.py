from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> Optional[str]:
    current_file = Path(__file__).resolve()
    backend_dir = current_file.parents[2]
    project_root = current_file.parents[3]

    candidates = [
        backend_dir / ".env",
        project_root / ".env",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_data_dir() -> str:
    return str(_project_root() / "data")


class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    argus_data_dir: str = Field(default_factory=_default_data_dir, alias="ARGUS_DATA_DIR")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(default=None, alias="CELERY_RESULT_BACKEND")
    job_max_retries: int = Field(default=2, alias="JOB_MAX_RETRIES", ge=0, le=10)
    job_retry_backoff_seconds: int = Field(default=30, alias="JOB_RETRY_BACKOFF_SECONDS", ge=1, le=3600)
    celery_task_time_limit_seconds: int = Field(default=3600, alias="CELERY_TASK_TIME_LIMIT_SECONDS", ge=60)
    celery_task_soft_time_limit_seconds: int = Field(
        default=3300,
        alias="CELERY_TASK_SOFT_TIME_LIMIT_SECONDS",
        ge=30,
    )
    monitor_schedule_scan_seconds: int = Field(
        default=300,
        alias="MONITOR_SCHEDULE_SCAN_SECONDS",
        ge=30,
        le=3600,
    )
    min_monitor_schedule_cadence_minutes: int = Field(
        default=60,
        alias="MIN_MONITOR_SCHEDULE_CADENCE_MINUTES",
        ge=60,
        le=10080,
    )
    monitor_first_run_lookback_days: int = Field(
        default=60,
        alias="MONITOR_FIRST_RUN_LOOKBACK_DAYS",
        ge=1,
        le=365,
    )
    monitor_subsequent_overlap_days: int = Field(
        default=7,
        alias="MONITOR_SUBSEQUENT_OVERLAP_DAYS",
        ge=0,
        le=90,
    )
    monitor_default_search_limit: int = Field(
        default=80,
        alias="MONITOR_RUN_SEARCH_LIMIT",
        ge=1,
        le=100,
    )
    monitor_default_max_cloud_cover: float = Field(
        default=40.0,
        alias="MONITOR_RUN_MAX_CLOUD_COVER",
        ge=0,
        le=100,
    )

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def effective_celery_broker_url(self) -> str:
        if self.celery_broker_url:
            return self.celery_broker_url
        return self.redis_url

    @property
    def effective_celery_result_backend(self) -> str:
        if self.celery_result_backend:
            return self.celery_result_backend
        return self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
