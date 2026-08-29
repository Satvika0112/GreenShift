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

    # ─── Real Data Sources ────────────────────────────────────────
    # Job workloads CSV (560 real jobs from greenshift_workloads_final.csv)
    job_data_path: str = Field(default="data/greenshift_workloads_final.csv", description="Path to workloads CSV")

    # ─── Indian Regional Tariff Data Sources ──────────────────────
    # Telangana (IN-TG) dual-tariff CSVs (HT-I(A) and HT-II(A))
    tariff_ht1_path: str = Field(default="data/telangana_tod_tariff_ht1a.csv", description="Path to Telangana HT-I(A) Industry General tariff CSV")
    tariff_ht2_path: str = Field(default="data/telangana_tod_tariff_ht2a.csv", description="Path to Telangana HT-II(A) Others tariff CSV")

    # Gujarat (IN-GJ) ToD tariff CSV (HTP-I)
    tariff_gj_path: str = Field(default="data/gujarat_tod_tariff_hourly_FY2026-27.csv", description="Path to Gujarat HTP-I tariff CSV")

    # Himachal Pradesh (IN-HP) Flat tariff CSV (Large Industry - EHT)
    tariff_hp_path: str = Field(default="data/himachal_pradesh_flat_tariff_hourly_FY2026-27.csv", description="Path to Himachal Pradesh Large Industry flat tariff CSV")

    # West Bengal (IN-WB) ToD tariff CSV (Industries Rate E-BT)
    tariff_wb_path: str = Field(default="data/west_bengal_tod_tariff_hourly_FY2026-27.csv", description="Path to West Bengal Industries tariff CSV")

    # Job-type to tariff-category mapping (comma-separated; industrial types → HT-I(A) / Industrial)
    tariff_industrial_types: str = Field(
        default="DATA_PROCESSING,ETL,HPC,BATCH,SIMULATION",
        description="Comma-separated job types that map to HT-I(A) / Industrial tariff",
    )

    # FX Conversion rate from INR to USD (used for normalized cost comparison)
    tariff_inr_to_usd: float = Field(
        default=0.012,
        description="Conversion rate from INR to USD for electricity cost calculation",
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

