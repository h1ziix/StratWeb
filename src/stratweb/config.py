"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Importing the package never creates files or directories."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="STRATWEB_",
        extra="ignore",
    )

    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    data_dir: Path = Path("data")
    duckdb_path: Path = Path("data/stratweb.duckdb")
    map_overview_dir: Path = Path("data/map_overviews")
    max_upload_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0)
    position_sample_interval_ticks: int = Field(default=16, gt=0)
    map_developer_mode: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""

    return Settings()
