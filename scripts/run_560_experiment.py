"""
GreenShift 560-Job Fleet Experiment Runner.
Runs the full workload dataset through INGEST -> DECIDE, then computes
comprehensive fleet impact analytics with regional breakdowns, distribution data,
and formatted reports.

Usage:
  python scripts/run_560_experiment.py
  python scripts/run_560_experiment.py --output-dir results/experiment-001
  python scripts/run_560_experiment.py --max-jobs 100
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# Ensure project root in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.analytics.fleet_impact import FleetImpactReport, compute_fleet_impact
from app.arrival.simulator import (
    ArrivalJobState,
    DynamicArrivalSimulator,
    SimulationConfig,
    SimulationJobRecord,
)
from app.shared.database import SessionLocal, init_db
from app.shared.models import JobORM, ScheduleDecisionORM

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("greenshift.experiment")


def generate_experiment_id() -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"EXP-{now_str}-{short_uuid}"


def export_per_job_csv(db: SessionLocal, filepath: Path) -> int:
    query = (
        db.query(ScheduleDecisionORM, JobORM)
        .join(JobORM, ScheduleDecisionORM.job_id == JobORM.job_id)
        .order_by(JobORM.job_id.asc())
    )
    rows = query.all()

    inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", "0.012"))
    if inr_to_usd <= 0:
        inr_to_usd = 0.012

    headers = [
        "job_id",
        "team_id",
        "job_type",
        "region",
        "energy_kwh",
        "runtime_minutes",
        "selected_start",
        "selected_end",
        "carbon_intensity",
        "carbon_emission_kg",
        "baseline_carbon_emission_kg",
        "carbon_avoided_kg",
        "carbon_reduction_pct",
        "electricity_cost_usd",
        "baseline_cost_usd",
        "cost_difference_usd",
        "cost_reduction_pct",
        "native_cost_inr",
        "baseline_native_cost_inr",
        "cost_saved_inr",
        "scheduling_delay_hours",
        "sla_met",
        "tariff_plan",
        "scheduling_method",
        "slot_utilization_pct",
        "demand_predicted",
        "spilled_from_preferred",
        "ml_advisor_used",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for sd, job in rows:
            b_carb = sd.baseline_carbon_emission if sd.baseline_carbon_emission is not None else sd.carbon_emission
            c_avoided = sd.carbon_avoided if sd.carbon_avoided is not None else (b_carb - sd.carbon_emission)
            b_cost = sd.baseline_cost if sd.baseline_cost is not None else sd.electricity_cost
            cost_diff = sd.cost_difference if sd.cost_difference is not None else (b_cost - sd.electricity_cost)
            gs_inr = sd.native_cost if sd.native_cost is not None else (sd.electricity_cost / inr_to_usd)
            b_inr = sd.baseline_native_cost if sd.baseline_native_cost is not None else (b_cost / inr_to_usd)

            writer.writerow([
                job.job_id,
                job.team_id,
                job.job_type,
                sd.region_id or job.region,
                round(float(job.energy_kwh or 0.0), 3),
                job.runtime_minutes,
                sd.selected_start.isoformat() if sd.selected_start else "",
                sd.selected_end.isoformat() if sd.selected_end else "",
                round(float(sd.carbon_intensity or 0.0), 2),
                round(float(sd.carbon_emission or 0.0), 6),
                round(float(b_carb or 0.0), 6),
                round(float(c_avoided or 0.0), 6),
                round(float(sd.carbon_reduction_pct or 0.0), 2),
                round(float(sd.electricity_cost or 0.0), 6),
                round(float(b_cost or 0.0), 6),
                round(float(cost_diff or 0.0), 6),
                round(float(sd.cost_reduction_pct or 0.0), 2),
                round(float(gs_inr or 0.0), 2),
                round(float(b_inr or 0.0), 2),
                round(float(b_inr - gs_inr), 2),
                round(float(sd.scheduling_delay_hours or 0.0), 2),
                bool(sd.sla_met if sd.sla_met is not None else True),
                sd.tariff_plan or "",
                sd.scheduling_method or "single_greedy",
                round(float(sd.slot_utilization_pct or 0.0), 1),
                round(float(sd.demand_predicted or 0.0), 4),
                bool(sd.spilled_from_preferred or False),
                bool(sd.ml_advisor_used or False),
            ])

    return len(rows)


def export_headline_markdown(report: FleetImpactReport, filepath: Path) -> None:
    content = f"""# GreenShift Fleet Experiment Results
**Experiment ID**: `{report.experiment_id}`  
**Generated At**: {report.generated_at}  
**Workloads Evaluated**: {report.total_jobs_with_decisions} / {report.total_jobs_analyzed}

## Headline Impact Summary

| Metric | Baseline (Immediate) | GreenShift (Optimized) | Savings / Impact |
|---|---|---|---|
| **Carbon Emissions** | {report.total_baseline_carbon_kg:,.2f} kg CO₂ | {report.total_greenshift_carbon_kg:,.2f} kg CO₂ | **{report.total_carbon_avoided_kg:,.2f} kg CO₂ avoided ({report.avg_carbon_reduction_pct:.1f}% mean red.)** |
| **Electricity Cost (USD)** | ${report.total_baseline_cost_usd:,.2f} | ${report.total_greenshift_cost_usd:,.2f} | **${report.total_cost_saved_usd:,.2f} saved ({report.avg_cost_reduction_pct:.1f}% mean red.)** |
| **Electricity Cost (INR)** | ₹{report.total_baseline_cost_inr:,.0f} | ₹{report.total_greenshift_cost_inr:,.0f} | **₹{report.total_cost_saved_inr:,.0f} saved** |
| **Total Energy** | — | — | **{report.total_energy_kwh:,.1f} kWh** |
| **Scheduling Delay** | 0.0 hrs | {report.avg_scheduling_delay_hours:.1f} hrs | **Mean deferral** |
| **SLA Compliance** | 100.0% | **{report.sla_compliance_pct:.1f}%** | **{report.sla_met_count} met, {report.sla_miss_count} missed** |
| **Median Carbon Reduction** | — | — | **{report.median_carbon_reduction_pct:.1f}%** |
| **P90 Carbon Reduction** | — | — | **{report.p90_carbon_reduction_pct:.1f}%** |
| **Positive Carbon Jobs** | — | — | **{report.jobs_with_positive_carbon_savings} / {report.total_jobs_with_decisions}** |

## Regional Breakdown

| Region | Jobs | Carbon Avoided (kg) | Avg Carbon Red. % | Cost Saved (USD) | Cost Saved (INR) | SLA % |
|---|---|---|---|---|---|---|
"""
    for reg, sumry in report.by_region.items():
        content += f"| **{reg}** | {sumry.job_count} | {sumry.total_carbon_avoided_kg:,.2f} kg | {sumry.avg_carbon_reduction_pct:.1f}% | ${sumry.total_cost_saved_usd:,.2f} | ₹{sumry.total_cost_saved_inr:,.0f} | {sumry.sla_compliance_pct:.1f}% |\n"

    content += f"""
## Pitch / Paper One-Liner
> *"GreenShift reduced carbon emissions by {report.avg_carbon_reduction_pct:.1f}% and saved ₹{report.total_cost_saved_inr:,.0f} across {report.total_jobs_with_decisions} compute workloads spanning {len(report.by_region)} Indian grid regions, while maintaining {report.sla_compliance_pct:.1f}% SLA compliance."*
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="GreenShift 560-Workload Fleet Experiment")
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/greenshift_workloads_final.csv",
        help="Path to workload dataset CSV",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=0.0,
        help="Simulation speed multiplier (0.0 = instant discrete jumps)",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Maximum jobs to simulate (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="Directory to store experiment reports and artifacts",
    )
    parser.add_argument(
        "--experiment-id",
        type=str,
        default=None,
        help="Optional custom experiment ID",
    )
    parser.add_argument(
        "--use-batch",
        action="store_true",
        default=False,
        help="Use Contention-Aware Batch Scheduler (Layer 1 Slot Capacity + Layer 2 ML Advisor)",
    )
    parser.add_argument(
        "--no-ml",
        action="store_true",
        default=False,
        help="Disable Layer 2 ML Advisor during batch scheduling",
    )
    args = parser.parse_args()

    exp_id = args.experiment_id or generate_experiment_id()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    mode_str = "Contention-Aware Batch (Layer 1 + Layer 2 ML)" if (args.use_batch and not args.no_ml) else ("Contention-Aware Batch (Layer 1 Capacity Only)" if args.use_batch else "Single-Job Greedy (Baseline)")

    print("=" * 70)
    print("  🌿 GREENSHIFT 560-JOB FLEET IMPACT EXPERIMENT")
    print("=" * 70)
    print(f"  Experiment ID : {exp_id}")
    print(f"  Scheduling    : {mode_str}")
    print(f"  Dataset Path  : {args.dataset}")
    print(f"  Max Jobs Cap  : {args.max_jobs or 'All Dataset Workloads'}")
    print(f"  Output Dir    : {out_dir}")
    print("=" * 70)

    # 1. Initialize DB
    init_db()
    db = SessionLocal()

    # 2. Simulator Configuration
    config = SimulationConfig(
        dataset_path=args.dataset,
        simulation_speed=args.speed,
        max_jobs=args.max_jobs,
        auto_schedule=not args.use_batch,
    )

    processed_count = [0]
    last_print = [0]

    def on_progress(sim_time: datetime, released: List[SimulationJobRecord]):
        processed_count[0] += len(released)
        if processed_count[0] - last_print[0] >= 50 or processed_count[0] == 1:
            print(f"  [Progress] Ingested {processed_count[0]} workloads...")
            last_print[0] = processed_count[0]

    if args.use_batch:
        print("\n[PHASE 1] Ingesting workloads into database (batch queue mode)...")
        simulator = DynamicArrivalSimulator(config=config, db=db)
        summary = simulator.run(progress_callback=on_progress, db=db)
        print(f"  ✓ Ingestion complete: {summary.jobs_submitted_successfully} workloads queued.")

        # Batch schedule with contention awareness
        from app.decide.service import schedule_batch_and_store
        from app.shared.models import JobStatus

        submitted_jobs = db.query(JobORM).filter(JobORM.status == JobStatus.SUBMITTED).all()
        print(f"\n[PHASE 1B] Batch scheduling {len(submitted_jobs)} workloads with Layer 1 Slot Capacity and {'Layer 2 ML Advisor' if not args.no_ml else 'Capacity Only'}...")
        batch_decisions = schedule_batch_and_store(
            db=db,
            jobs=submitted_jobs,
            use_demand_forecast=not args.no_ml,
            record_audit=False,
        )
        spilled_count = sum(1 for d in batch_decisions if getattr(d, "spilled_from_preferred", False))
        spill_pct = (spilled_count / len(batch_decisions) * 100.0) if batch_decisions else 0.0
        print(f"  ✓ Batch scheduling complete: {len(batch_decisions)} scheduled | {spilled_count} spilled from preferred slot ({spill_pct:.1f}% spillover).\n")
    else:
        print("\n[PHASE 1] Ingesting and scheduling workloads through DECIDE engine...")
        simulator = DynamicArrivalSimulator(config=config, db=db)
        summary = simulator.run(progress_callback=on_progress, db=db)
        print(f"  ✓ Ingestion complete: {summary.jobs_submitted_successfully} workloads scheduled successfully.\n")

    # 3. Compute Fleet Impact Analytics
    print("[PHASE 2] Computing comprehensive fleet impact analytics...")
    report = compute_fleet_impact(db, experiment_id=exp_id)

    # 4. Generate & Print Terminal Headline
    pos_pct = (report.jobs_with_positive_carbon_savings / report.total_jobs_with_decisions * 100.0) if report.total_jobs_with_decisions else 0.0

    print("\n" + "═" * 70)
    print("  🌿 GREENSHIFT 560-JOB FLEET EXPERIMENT — RESULTS")
    print("═" * 70)
    print(f"\n  HEADLINE IMPACT:")
    print(f"    Total Workloads Optimized   : {report.total_jobs_with_decisions}")
    print(f"    Total Energy Consumed       : {report.total_energy_kwh:,.1f} kWh")
    print("")
    print(f"    Carbon Emissions (Baseline) : {report.total_baseline_carbon_kg:,.1f} kg CO₂")
    print(f"    Carbon Emissions (GreenShift): {report.total_greenshift_carbon_kg:,.1f} kg CO₂")
    print(f"    Carbon Avoided              : {report.total_carbon_avoided_kg:,.1f} kg CO₂  ({report.avg_carbon_reduction_pct:.1f}% reduction)")
    print("")
    print(f"    Electricity Cost (Baseline) : ${report.total_baseline_cost_usd:,.2f} USD  /  ₹{report.total_baseline_cost_inr:,.0f} INR")
    print(f"    Electricity Cost (GreenShift): ${report.total_greenshift_cost_usd:,.2f} USD  /  ₹{report.total_greenshift_cost_inr:,.0f} INR")
    print(f"    Cost Saved                  : ${report.total_cost_saved_usd:,.2f} USD  /  ₹{report.total_cost_saved_inr:,.0f} INR  ({report.avg_cost_reduction_pct:.1f}% savings)")
    print("")
    print(f"    Average Scheduling Delay    : {report.avg_scheduling_delay_hours:.1f} hours")
    print(f"    SLA Compliance              : {report.sla_met_count} / {report.total_jobs_with_decisions} ({report.sla_compliance_pct:.1f}%)")
    print("")
    print(f"    Jobs with Carbon Savings    : {report.jobs_with_positive_carbon_savings} / {report.total_jobs_with_decisions} ({pos_pct:.1f}%)")
    print(f"    Median Carbon Reduction     : {report.median_carbon_reduction_pct:.1f}%")
    print(f"    P90 Carbon Reduction        : {report.p90_carbon_reduction_pct:.1f}%")

    contention_decisions = db.query(ScheduleDecisionORM).all()
    if any(sd.slot_utilization_pct is not None for sd in contention_decisions):
        spill_cnt = sum(1 for sd in contention_decisions if getattr(sd, "spilled_from_preferred", False))
        ml_used_cnt = sum(1 for sd in contention_decisions if getattr(sd, "ml_advisor_used", False))
        max_util = max((sd.slot_utilization_pct or 0.0 for sd in contention_decisions), default=0.0)
        avg_util = (sum(sd.slot_utilization_pct or 0.0 for sd in contention_decisions) / len(contention_decisions)) if contention_decisions else 0.0
        print("\n  CONTENTION & CAPACITY INTELLIGENCE:")
        print(f"    Spilled from Preferred Slot : {spill_cnt} / {len(contention_decisions)} ({(spill_cnt/len(contention_decisions)*100.0) if contention_decisions else 0.0:.1f}%)")
        print(f"    Max Slot CPU Utilization    : {max_util:.1f}%")
        print(f"    Average Slot Utilization    : {avg_util:.1f}%")
        print(f"    ML Advisor Guidance Applied : {ml_used_cnt} workloads")

    print("\n  REGIONAL BREAKDOWN:")
    for reg_id, r_sumry in sorted(report.by_region.items()):
        print(f"    {reg_id:<12} : {r_sumry.job_count:>3} jobs | {r_sumry.avg_carbon_reduction_pct:>5.1f}% carbon | ₹{r_sumry.total_cost_saved_inr:>6,.0f} saved (USD ${r_sumry.total_cost_saved_usd:,.2f})")

    print("═" * 70)

    # 5. Export Output Artifacts
    print(f"\n[PHASE 3] Writing structured artifacts to '{out_dir}'...")

    # A. JSON summary
    summary_path = out_dir / "experiment_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)
    print(f"  ✓ Saved {summary_path}")

    # B. Per-job CSV
    csv_path = out_dir / "experiment_per_job.csv"
    csv_rows = export_per_job_csv(db, csv_path)
    print(f"  ✓ Saved {csv_path} ({csv_rows} rows)")

    # C. Headline Markdown
    md_path = out_dir / "experiment_headline.md"
    export_headline_markdown(report, md_path)
    print(f"  ✓ Saved {md_path}")

    # D. Distributions JSON
    dist_path = out_dir / "experiment_distributions.json"
    dist_payload = {
        "carbon_reduction": report.carbon_reduction_distribution,
        "cost_reduction": report.cost_reduction_distribution,
        "delay_hours": report.delay_hours_distribution,
        "baseline_hours": report.baseline_hour_distribution,
        "greenshift_hours": report.greenshift_hour_distribution,
    }
    with open(dist_path, "w", encoding="utf-8") as f:
        json.dump(dist_payload, f, indent=2)
    print(f"  ✓ Saved {dist_path}")

    # 6. Copy-Paste One-Liner for Judges
    print("\n" + "─" * 70)
    print("  📋 COPY-PASTE FOR JUDGES:")
    print(
        f'  "GreenShift reduced carbon emissions by {report.avg_carbon_reduction_pct:.1f}% and saved ₹{report.total_cost_saved_inr:,.0f} '
        f"across {report.total_jobs_with_decisions} compute workloads spanning {len(report.by_region)} Indian grid regions, "
        f'while maintaining {report.sla_compliance_pct:.1f}% SLA compliance."'
    )
    print("─" * 70 + "\n")

    db.close()


if __name__ == "__main__":
    main()
