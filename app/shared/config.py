"""
GreenShift — Application settings loaded from environment variables / .env file.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Carbon API ───────────────────────────────────────────────
    electricity_maps_api_key: str = Field(default="")
    carbon_api_base_url: str = Field(
        default="https://api.electricitymap.org/v3",
    )

    # ─── Tariff API ───────────────────────────────────────────────
    tariff_api_key: str = Field(default="")
    tariff_api_base_url: str = Field(
        default="https://api.example-tariff.com/v1",
    )

    # ─── Database ─────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./greenshift.db",
    )

    # ─── Kubernetes ───────────────────────────────────────────────
    k8s_namespace: str = Field(default="greenshift")
    k8s_in_cluster: bool = Field(default=False)

    # ─── Application ──────────────────────────────────────────────
    log_level: str    = Field(default="INFO")
    api_host: str     = Field(default="0.0.0.0")
    api_port: int     = Field(default=8000)
    environment: str  = Field(default="development")

    # ─── Cache ────────────────────────────────────────────────────
    cache_ttl_seconds: int = Field(default=300)

    # ─── Dispatcher poll ──────────────────────────────────────────
    dispatcher_poll_interval_seconds: int = Field(default=30)


settings = Settings()
