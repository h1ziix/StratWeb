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
    # Loopback by default: the API has no authentication. Docker/LAN deployments
    # must opt in explicitly via STRATWEB_HOST.
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    data_dir: Path = Path("data")
    duckdb_path: Path = Path("data/stratweb.duckdb")
    map_overview_dir: Path = Path("data/map_overviews")
    # Optional game/csgo or game/csgo/StratWeb path used only after a local button press.
    cs2_demo_dir: Path | None = None
    max_upload_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0)
    max_batch_upload_bytes: int = Field(default=8 * 1024 * 1024 * 1024, gt=0)
    position_sample_interval_ticks: int = Field(default=16, gt=0)
    import_queue_size: int = Field(default=16, ge=0, le=100)
    parser_timeout_seconds: int = Field(default=1800, ge=10)
    parser_memory_limit_bytes: int = Field(default=4 * 1024 * 1024 * 1024, gt=0)
    import_minimum_free_disk_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=0)
    import_cancel_grace_seconds: float = Field(default=5.0, ge=0.1, le=60)
    map_developer_mode: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""

    return Settings()
