"""
GreenShift — Application settings loaded from environment variables / .env file.
"""

from typing import Optional
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


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
        default="https://api.electricitymaps.com/v4",
    )

    # ─── Tariff API ───────────────────────────────────────────────
    tariff_api_key: str = Field(default="")
    tariff_api_base_url: str = Field(
        default="https://api.example-tariff.com/v1",
    )

    # ─── Database ─────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./greenshift.db",
        description="Database connection URL (PostgreSQL in production, SQLite in local dev)",
    )
    postgres_db: str = Field(default="greenshift")
    postgres_user: str = Field(default="greenshift")
    postgres_password: str = Field(default="greenshift_secret_pwd")
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    db_pool_size: int = Field(default=10)
    db_max_overflow: int = Field(default=20)
    db_pool_recycle_seconds: int = Field(default=1800)

    # ─── Kubernetes ───────────────────────────────────────────────
    k8s_namespace: str = Field(default="greenshift")
    k8s_in_cluster: bool = Field(default=False)
    kubeconfig_path: Optional[str] = Field(
        default=None,
        description="Optional custom path to kubeconfig file",
    )
    k8s_host_override: Optional[str] = Field(
        default=None,
        description="Optional Kubernetes API server host override (e.g. https://host.docker.internal:63799)",
    )
    k8s_insecure_skip_tls_verify: bool = Field(
        default=False,
        description="Set True to skip TLS certificate verification if connecting via rewritten hostnames",
    )

    # ─── Application ──────────────────────────────────────────────
    log_level: str    = Field(default="INFO")
    api_host: str     = Field(default="0.0.0.0")
    api_port: int     = Field(default=8000)
    environment: str  = Field(default="development")

    # ─── Cache & Redis ────────────────────────────────────────────
    cache_ttl_seconds: int = Field(default=300)
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for shared Carbon API cache",
    )
    redis_connect_timeout: float = Field(
        default=2.0,
        description="Timeout in seconds for connecting to Redis",
    )

    # ─── Dispatcher poll ──────────────────────────────────────────
    dispatcher_poll_interval_seconds: int = Field(default=5)
    dispatch_poll_seconds: int = Field(default=5)
    status_refresh_seconds: int = Field(default=5)

    # ─── Real Data Sources ────────────────────────────────────────
    # Job workloads CSV (560 real jobs from greenshift_workloads_final.csv)
    job_data_path: str = Field(default="data/greenshift_workloads_final.csv", description="Path to workloads CSV")

    # ─── Master ToD Tariff Dataset (Single Source of Truth) ──────
    # 264-row dataset across IN-TG, IN-GJ, IN-WB, IN-PB, US-CA, US-NY, US-TX, SE, AU-SA-Large, AU-SA-Small
    master_tariff_dataset: str = Field(
        default="data/master_tod_tariff_all_regions.csv",
        description="Path to Master ToD Regional Tariff CSV",
    )

    # Job-type to tariff-category mapping (comma-separated; industrial types → HT-I(A) / Industrial)
    tariff_industrial_types: str = Field(
        default="DATA_PROCESSING,ETL,HPC,BATCH,SIMULATION",
        description="Comma-separated job types that map to HT-I(A) / Industrial tariff",
    )

    # FX Conversion rates to USD (used for normalized cost comparison)
    tariff_inr_to_usd: float = Field(
        default=0.012,
        description="Conversion rate from INR to USD for electricity cost calculation",
    )
    tariff_sek_to_usd: float = Field(
        default=0.095,
        description="Conversion rate from SEK to USD for electricity cost calculation",
    )
    tariff_aud_to_usd: float = Field(
        default=0.65,
        description="Conversion rate from AUD to USD for electricity cost calculation",
    )

    # Default carbon region (used by ingest loop if no per-job region specified)
    carbon_region: str = Field(default="IN-SO", description="Default grid zone for carbon data")

    # ─── Dynamic Arrival Simulation ───────────────────────────────
    simulation_speed: float = Field(
        default=60.0,
        description="Speed multiplier for arrival simulation (e.g. 60.0 = 1 real sec is 60 sim sec)",
    )
    simulation_step_seconds: float = Field(
        default=60.0,
        description="Simulation clock step resolution in simulated seconds",
    )

    # ─── Data Resilience & Carbon Fallback Layer ──────────────────
    carbon_cache_ttl_seconds: int = Field(
        default=900,
        description="Carbon cache time-to-live in seconds (default: 15 min / 900s)",
    )
    carbon_fallback_gco2_per_kwh: float = Field(
        default=400.0,
        description="Controlled deterministic carbon fallback value in gCO2/kWh",
    )
    simulate_carbon_api_down: bool = Field(
        default=False,
        description="Simulate Electricity Maps API outage for resilience testing & demonstrations",
    )
    carbon_csv_path: Optional[str] = Field(
        default=None,
        description="Optional path to historical regional carbon CSV dataset",
    )

    # Synthetic/mock data gates — set to false to REQUIRE real data sources
    allow_synthetic_carbon: bool = Field(
        default=True,
        description="Allow synthetic carbon data when API is unavailable",
    )
    allow_synthetic_tariff: bool = Field(
        default=True,
        description="Allow synthetic tariff data when no CSV is configured",
    )


settings = Settings()

