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

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
