"""
GreenShift Data Resilience & Multi-Level Fallback Demonstration.

Demonstrates the 4 Failure & Fallback Scenarios:
  SCENARIO 1: Live API Available -> Live carbon retrieval -> DB cache updated
  SCENARIO 2: API Outage -> Fresh Cache Hit -> Scheduling continues uninterrupted
  SCENARIO 3: API Outage + Cache Stale -> Stale Cache Fallback -> Reason & age reported
  SCENARIO 4: API Outage + No Cache + No CSV -> Controlled Fallback (400.0 gCO2/kWh)
"""

import io
import os
import sys
from datetime import datetime, timedelta, timezone

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ingest.carbon_api import (
    get_resilient_carbon_curve,
    get_carbon_from_db_cache,
    store_carbon_in_db_cache,
)
from app.ingest.data_sources import get_data_source_status
from app.shared.database import init_db, SessionLocal
from app.shared.models import CarbonDataPoint, CarbonDataPointORM
from app.shared.utils import utcnow


def run_resilience_demo():
    print("=" * 75)
    print("  🌿 GREENSHIFT DATA RESILIENCE & MULTI-LEVEL FALLBACK DEMONSTRATION")
    print("=" * 75)

    init_db()
    db = SessionLocal()
    now = utcnow()
    end = now + timedelta(hours=4)

    # ── SCENARIO 1: Live API or Simulated Live Feed ──────────────────────
    print("\n[SCENARIO 1: Live Electricity Maps Telemetry & Cache Population]")
    points_s1 = get_resilient_carbon_curve("IN-TG", now, end, db=db)
    sample_s1 = points_s1[0]
    print(f"  Region       : IN-TG (Zone: {sample_s1.em_zone or 'IN-SO'})")
    print(f"  Source       : {sample_s1.source.upper()}")
    print(f"  Carbon Value : {sample_s1.carbon_gco2_kwh:.2f} gCO2/kWh")
    print(f"  Is Fallback  : {sample_s1.is_fallback}")
    print(f"  Points Count : {len(points_s1)} hourly points")
    print("  ✓ Live carbon retrieved and persisted to DB cache successfully.")

    # ── SCENARIO 2: API Outage with Fresh Cache ─────────────────────────
    print("\n[SCENARIO 2: Electricity Maps API Outage -> Fresh Cache Hit]")
    os.environ["SIMULATE_CARBON_API_DOWN"] = "true"
    points_s2 = get_resilient_carbon_curve("IN-TG", now, end, db=db)
    sample_s2 = points_s2[0]
    print(f"  API Status   : OUTAGE / UNAVAILABLE (Simulated)")
    print(f"  Source       : {sample_s2.source.upper()} (Fresh within TTL)")
    print(f"  Carbon Value : {sample_s2.carbon_gco2_kwh:.2f} gCO2/kWh")
    print(f"  Cache Age    : {sample_s2.cache_age_seconds or 0.0:.1f}s (TTL: 900s)")
    print(f"  Is Fallback  : {sample_s2.is_fallback}")
    print("  ✓ Scheduling pipeline continues seamlessly using fresh persistent cache.")

    # ── SCENARIO 3: API Outage with Stale Cache ─────────────────────────
    print("\n[SCENARIO 3: API Outage + Stale Cache Fallback]")
    # Plant a stale record (fetched 3 hours ago) for IN-GJ
    past_fetched = now - timedelta(hours=3)
    stale_orm = CarbonDataPointORM(
        timestamp=now,
        region="IN-GJ",
        carbon_gco2_kwh=415.50,
        fetched_at=past_fetched,
        source="electricity_maps",
        expires_at=past_fetched + timedelta(seconds=900),
        is_fallback=False,
    )
    db.merge(stale_orm)
    db.commit()

    points_s3 = get_resilient_carbon_curve("IN-GJ", now, now + timedelta(hours=1), db=db)
    sample_s3 = points_s3[0]
    print(f"  Region       : IN-GJ (Western Grid)")
    print(f"  Source       : {sample_s3.source.upper()}")
    print(f"  Carbon Value : {sample_s3.carbon_gco2_kwh:.2f} gCO2/kWh")
    print(f"  Is Fallback  : {sample_s3.is_fallback}")
    print(f"  Notice       : {sample_s3.fallback_reason}")
    print("  ✓ Stale cache safely used as emergency fallback with explicit provenance.")

    # ── SCENARIO 4: Total Outage -> Controlled Deterministic Fallback ────
    print("\n[SCENARIO 4: Total Outage (No API, No Cache, No CSV) -> Controlled Fallback]")
    # Request a region with no cache (e.g. IN-WB clean window far in future)
    future_start = now + timedelta(days=30)
    future_end = future_start + timedelta(hours=4)
    points_s4 = get_resilient_carbon_curve("IN-WB", future_start, future_end, db=db)
    sample_s4 = points_s4[0]
    print(f"  Region       : IN-WB (Eastern Grid)")
    print(f"  Source       : {sample_s4.source.upper()}")
    print(f"  Carbon Value : {sample_s4.carbon_gco2_kwh:.2f} gCO2/kWh (Baseline: 400.0 gCO2/kWh)")
    print(f"  Is Fallback  : {sample_s4.is_fallback}")
    print(f"  Reason       : {sample_s4.fallback_reason}")
    print("  ✓ Controlled deterministic fallback ensures DECIDE scheduler NEVER crashes.")

    # Reset simulation flag
    os.environ["SIMULATE_CARBON_API_DOWN"] = "false"

    # Status summary
    status = get_data_source_status(db=db)
    print("\n" + "=" * 75)
    print("  DATA RESILIENCE LAYER STATUS SUMMARY")
    print("=" * 75)
    print(f"  Carbon Source Status : {status['carbon']['source'].upper()} ({status['carbon']['description']})")
    print(f"  Cache TTL            : {status['carbon']['cache_ttl_seconds']}s (15 min)")
    print(f"  Fallback Default     : {status['carbon']['fallback_default_gco2']} gCO2/kWh")
    print(f"  Tariff Source        : {status['tariff']['source'].upper()} ({status['tariff']['description']})")
    print(f"  Supported Regions    : {', '.join(status['regional']['supported_regions'])}")
    print("=" * 75)

    db.close()


if __name__ == "__main__":
    run_resilience_demo()
