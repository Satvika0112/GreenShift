"""
CLI Runner for Dynamic Workload Arrival Simulation.

Usage:
  python -m scripts.run_arrival_simulation --speed 60 --max-jobs 20
  python scripts/run_arrival_simulation.py --speed 120 --dataset data/greenshift_workloads_final.csv
  python scripts/run_arrival_simulation.py --speed 0  # Discrete fast-forward
"""

import argparse
import io
import logging
import os
import sys
from datetime import datetime, timezone

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.arrival.simulator import (
    ArrivalJobState,
    DynamicArrivalSimulator,
    SimulationConfig,
    SimulationJobRecord,
)
from app.shared.database import init_db, SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("greenshift.arrival")


def main():
    parser = argparse.ArgumentParser(description="GreenShift Dynamic Workload Arrival Simulator")
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/greenshift_workloads_final.csv",
        help="Path to workload dataset CSV (default: data/greenshift_workloads_final.csv)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=60.0,
        help="Simulation speed multiplier (default: 60.0, e.g. 1s real = 60s sim. Set <=0 for instant jump mode)",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Maximum jobs to simulate (e.g. 20, or omit for all dataset jobs)",
    )
    parser.add_argument(
        "--start-time",
        type=str,
        default=None,
        help="Optional ISO-8601 simulation start time (e.g. '2026-04-01T09:00:00Z')",
    )
    parser.add_argument(
        "--step-seconds",
        type=float,
        default=60.0,
        help="Simulated seconds advanced per step tick (default: 60.0)",
    )

    args = parser.parse_args()

    print("=" * 75)
    print("  🌿 GREENSHIFT DYNAMIC WORKLOAD ARRIVAL SIMULATOR")
    print("=" * 75)
    print(f"  Dataset Path   : {args.dataset}")
    print(f"  Speed Multiplier: {args.speed:.1f}x ({'Instant Discrete Jump' if args.speed <= 0 else 'Accelerated Real-Time'})")
    print(f"  Max Jobs Cap   : {args.max_jobs or 'All Dataset Workloads'}")
    print("=" * 75)

    # Initialize Database Schema & Migrations
    init_db()
    db = SessionLocal()

    start_dt = None
    if args.start_time:
        start_dt = datetime.fromisoformat(args.start_time.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

    config = SimulationConfig(
        dataset_path=args.dataset,
        simulation_speed=args.speed,
        max_jobs=args.max_jobs,
        simulation_start_time=start_dt,
        step_size_seconds=args.step_seconds,
        auto_schedule=True,
    )

    def on_progress(sim_time: datetime, released: list[SimulationJobRecord]):
        for job in released:
            backlog_flag = " [BACKLOG]" if job.is_backlog else ""
            status_symbol = "✓" if job.state == ArrivalJobState.SUBMITTED_TO_INGEST else "✗"
            print(
                f"  [{sim_time.strftime('%Y-%m-%d %H:%M:%S')}] {status_symbol} Released {job.job_id} "
                f"(submit_time: {job.submit_time.strftime('%H:%M:%S')}, "
                f"type: {job.job_dict.get('job_type')}, "
                f"region: {job.job_dict.get('region')}){backlog_flag}"
            )

    simulator = DynamicArrivalSimulator(config=config, db=db)
    print(f"\n[SIMULATION INITIALIZED] Total jobs loaded: {len(simulator.jobs)}")
    print(f"[SIMULATION START TIME] {simulator.simulation_start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    summary = simulator.run(progress_callback=on_progress, db=db)

    print("\n" + "=" * 75)
    print("  SIMULATION RUN COMPLETE")
    print("=" * 75)
    print(f"  Total Jobs Evaluated          : {summary.total_jobs}")
    print(f"  Jobs Released                 : {summary.jobs_released}")
    print(f"  Initial Backlog Jobs          : {summary.backlog_jobs_count}")
    print(f"  Successfully Ingested & Decide: {summary.jobs_submitted_successfully}")
    print(f"  Ingest Failures               : {summary.jobs_failed}")
    print(f"  Real Elapsed Time             : {summary.duration_real_seconds:.2f} seconds")
    print(f"  Simulated Elapsed Time        : {summary.duration_simulated_seconds:.2f} seconds ({summary.duration_simulated_seconds/3600.0:.2f} hours)")
    print("=" * 75)

    db.close()


if __name__ == "__main__":
    main()
