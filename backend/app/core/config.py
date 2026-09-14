from functools import lru_cache
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, Optional

from pydantic import Field, field_validator
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
    argus_auth_enabled: bool = Field(default=True, alias="ARGUS_AUTH_ENABLED")
    argus_jwt_secret: str = Field(
        default_factory=lambda: token_urlsafe(48),
        alias="ARGUS_JWT_SECRET",
        min_length=32,
    )
    argus_access_token_minutes: int = Field(default=15, alias="ARGUS_ACCESS_TOKEN_MINUTES", ge=5, le=1440)
    argus_refresh_token_days: int = Field(default=14, alias="ARGUS_REFRESH_TOKEN_DAYS", ge=1, le=90)
    argus_cookie_secure: bool = Field(default=False, alias="ARGUS_COOKIE_SECURE")
    argus_cookie_domain: str | None = Field(default=None, alias="ARGUS_COOKIE_DOMAIN")
    argus_cookie_samesite: str = Field(default="lax", alias="ARGUS_COOKIE_SAMESITE")
    argus_access_cookie_name: str = Field(default="argus_access_token", alias="ARGUS_ACCESS_COOKIE_NAME")
    argus_refresh_cookie_name: str = Field(default="argus_refresh_token", alias="ARGUS_REFRESH_COOKIE_NAME")
    argus_csrf_cookie_name: str = Field(default="argus_csrf_token", alias="ARGUS_CSRF_COOKIE_NAME")
    argus_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="ARGUS_ALLOWED_ORIGINS",
    )

    quota_default_max_monitors: int = Field(default=10, alias="ARGUS_QUOTA_MAX_MONITORS", ge=1, le=5000)
    quota_default_max_active_monitors: int = Field(default=10, alias="ARGUS_QUOTA_MAX_ACTIVE_MONITORS", ge=1, le=5000)
    quota_default_max_aoi_area_km2: float = Field(default=2000.0, alias="ARGUS_QUOTA_MAX_AOI_AREA_KM2", gt=0)
    quota_default_max_manual_runs_per_day: int = Field(default=20, alias="ARGUS_QUOTA_MAX_MANUAL_RUNS_PER_DAY", ge=1, le=100000)
    quota_default_max_observation_searches_per_day: int = Field(
        default=60,
        alias="ARGUS_QUOTA_MAX_OBSERVATION_SEARCHES_PER_DAY",
        ge=1,
        le=100000,
    )
    quota_default_max_semantic_runs_per_day: int = Field(default=30, alias="ARGUS_QUOTA_MAX_SEMANTIC_RUNS_PER_DAY", ge=1, le=100000)
    quota_default_max_concurrent_jobs: int = Field(default=3, alias="ARGUS_QUOTA_MAX_CONCURRENT_JOBS", ge=1, le=1000)

    rate_limit_login_per_minute: int = Field(default=20, alias="ARGUS_RATE_LIMIT_LOGIN_PER_MINUTE", ge=1, le=10000)
    rate_limit_register_per_hour: int = Field(default=30, alias="ARGUS_RATE_LIMIT_REGISTER_PER_HOUR", ge=1, le=10000)
    rate_limit_refresh_per_minute: int = Field(default=60, alias="ARGUS_RATE_LIMIT_REFRESH_PER_MINUTE", ge=1, le=10000)
    rate_limit_observation_search_per_minute: int = Field(
        default=30,
        alias="ARGUS_RATE_LIMIT_OBSERVATION_SEARCH_PER_MINUTE",
        ge=1,
        le=10000,
    )
    rate_limit_manual_run_per_minute: int = Field(default=20, alias="ARGUS_RATE_LIMIT_MANUAL_RUN_PER_MINUTE", ge=1, le=10000)

    email_provider: str = Field(default="none", alias="ARGUS_EMAIL_PROVIDER")
    email_from_address: str = Field(default="no-reply@example.com", alias="ARGUS_EMAIL_FROM")
    email_api_key: str | None = Field(default=None, alias="ARGUS_EMAIL_API_KEY")
    email_resend_api_url: str = Field(default="https://api.resend.com", alias="ARGUS_EMAIL_RESEND_API_URL")

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

    @field_validator("argus_cookie_samesite")
    @classmethod
    def validate_cookie_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("ARGUS_COOKIE_SAMESITE must be one of: lax, strict, none")
        return normalized

    @field_validator("argus_allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(part).strip() for part in value if str(part).strip()]
        raise ValueError("ARGUS_ALLOWED_ORIGINS must be a comma-separated string or list")

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
