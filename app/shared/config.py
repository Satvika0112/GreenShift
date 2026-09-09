"""
GreenShift — Application settings loaded from environment variables / .env file.
"""

from typing import Optional, List
from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

# Insecure default values that must NEVER be allowed in production
DEV_INSECURE_JWT_SECRETS = {
    "greenshift_jwt_super_secret_key_change_in_production_2026",
    "greenshift-dev-insecure-jwt-secret-do-not-use-in-production",
    "secret",
    "changeme",
    "default",
}


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
    postgres_password: str = Field(
        default="",
        description="PostgreSQL password. Must be configured via POSTGRES_PASSWORD in production.",
    )
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

    # ─── Application & Security ───────────────────────────────────
    log_level: str    = Field(default="INFO")
    api_host: str     = Field(default="0.0.0.0")
    api_port: int     = Field(default=8000)
    environment: str  = Field(
        default="development",
        description="Application environment: 'development', 'testing', or 'production'",
    )
    jwt_secret_key: str = Field(
        default="greenshift-dev-insecure-jwt-secret-do-not-use-in-production",
        description="Secret key used for signing JWT access tokens (set via JWT_SECRET_KEY in production)",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_expire_minutes: int = Field(default=1440, description="JWT token validity in minutes (24 hours)")
    auth_enabled: bool = Field(
        default=False,
        description=(
            "Enable JWT authentication and RBAC. Must be true when ENVIRONMENT=production. "
            "When false (default), all endpoints are open — acceptable ONLY in development."
        ),
    )
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:8000,http://localhost:8501,http://127.0.0.1:3000,http://127.0.0.1:5173,http://127.0.0.1:8000,http://127.0.0.1:8501",
        description="Comma-separated list of allowed CORS origins for API clients (configured via CORS_ORIGINS)",
    )
    internal_service_key: Optional[str] = Field(
        default=None,
        description="Optional shared secret key for authenticating internal service-to-service calls (configured via INTERNAL_SERVICE_KEY)",
    )
    enable_hsts: bool = Field(
        default=False,
        description="Explicitly enable Strict-Transport-Security headers (automatically enabled in production/HTTPS)",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Return parsed list of allowed CORS origins."""
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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

    @model_validator(mode="after")
    def _default_auth_enabled_for_env(self) -> "Settings":
        if "auth_enabled" not in self.model_fields_set:
            if (self.environment or "").strip().lower() == "production":
                self.auth_enabled = True
        return self


settings = Settings()


def validate_security_config(cfg: Optional[Settings] = None) -> None:
    """
    Validate application security configuration and secrets.
    Fails fast if production environment is detected with missing or insecure secrets.

    RULE 1: Production must refuse to start with auth disabled.
    RULE 2: Production must reject the default dev JWT secret.
    """
    if cfg is None:
        cfg = settings

    env = (cfg.environment or "").strip().lower()

    if env == "production":
        # 1. Validate JWT Secret length & dev defaults
        if not cfg.jwt_secret_key or cfg.jwt_secret_key in DEV_INSECURE_JWT_SECRETS:
            raise ValueError(
                "CRITICAL SECURITY ERROR: JWT_SECRET_KEY must be set to a cryptographically "
                "secure random secret in production (cannot be empty or default dev secret)."
            )
        if len(cfg.jwt_secret_key) < 32:
            raise ValueError(
                "CRITICAL SECURITY ERROR: JWT_SECRET_KEY must be at least 32 characters long in production."
            )

        # 2. Validate Database Password if PostgreSQL is used
        if cfg.database_url.startswith("postgres") or cfg.postgres_host not in ("localhost", "127.0.0.1"):
            if not cfg.postgres_password or cfg.postgres_password == "greenshift_secret_pwd":
                raise ValueError(
                    "CRITICAL SECURITY ERROR: POSTGRES_PASSWORD must be explicitly configured in production."
                )

        # 3. Validate CORS
        if "*" in cfg.cors_origins_list or (cfg.cors_origins and cfg.cors_origins.strip() == "*"):
            raise ValueError(
                "CRITICAL SECURITY ERROR: Wildcard CORS origin ('*') is forbidden in production."
            )

    # ── RULE 1: Production must always have auth enabled ──────────────────────
    if env == "production" and not cfg.auth_enabled:
        raise RuntimeError(
            "FATAL: AUTH_ENABLED=false in production environment. "
            "GreenShift refuses to start with an open API in production. "
            "Set AUTH_ENABLED=true or change ENVIRONMENT to 'development'."
        )

    # ── RULE 2: Auth enabled requires a real JWT secret ───────────────────────
    _DEV_SECRET = "greenshift-dev-insecure-jwt-secret-do-not-use-in-production"
    if cfg.auth_enabled and (
        not cfg.jwt_secret_key
        or cfg.jwt_secret_key in DEV_INSECURE_JWT_SECRETS
        or cfg.jwt_secret_key == _DEV_SECRET
    ):
        raise RuntimeError(
            "FATAL: JWT_SECRET_KEY is still the development default. "
            "Set a strong random secret via JWT_SECRET_KEY env var. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

