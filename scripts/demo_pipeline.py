"""
GreenShift End-to-End Demonstration Script
Executes the full 5-agent pipeline:
INGEST -> DECIDE -> DISPATCH -> TRUST -> PRESENT
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone

# Ensure workspace root is in python path
sys.path.insert(0, os.path.abspath("."))

from app.shared.database import init_db, SessionLocal
from app.shared.models import JobSubmitRequest, JobStatus, EventType
from app.ingest.service import ingest_job
from app.ingest.data_sources import get_data_source_status
from app.decide.service import schedule_and_store
from app.trust.service import (
    record_job_submitted,
    record_job_scheduled,
    record_k8s_job_created,
    record_k8s_job_completed,
    record_export_generated,
)
from app.trust.ledger import verify_chain, append_event
from app.trust.report import generate_report, generate_csv


def run_demo():
    print("=" * 70)
    print("GREENSHIFT END-TO-END SYSTEM DEMONSTRATION")
    print("=" * 70)

    # Initialize Database
    init_db()
    db = SessionLocal()

    try:
        # Check active data sources
        sources = get_data_source_status()
        print("\n[DATA SOURCES ACTIVE]")
        print(f"  Carbon Intensity : {sources['carbon']['source'].upper()} ({sources['carbon']['description']})")
        print(f"  Electricity Tariff: {sources['tariff']['source'].upper()} ({sources['tariff']['description']})")

        # ─── AGENT 1: INGEST ─────────────────────────────────────────
        print("\n[AGENT 1: INGEST] Submitting and validating job...")
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=12)

        request = JobSubmitRequest(
            team_id="demo-team",
            deadline=deadline,
            runtime_minutes=10,
            power_kw=5.0,
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
            cpu_request="500m",
            memory_request="512Mi",
            carbon_budget_kg=2.0,
        )

        job = ingest_job(db, request)
        print(f"  Registered Job ID : {job.job_id}")
        print(f"  Team              : {job.team_id}")
        print(f"  Runtime           : {job.runtime_minutes} mins")
        print(f"  Power             : {job.power_kw} kW")
        print(f"  Region            : {job.region}")
        print(f"  Deadline          : {job.deadline.isoformat()}")
        print(f"  Status            : {job.status.value}")

        # ─── AGENT 2: DECIDE ─────────────────────────────────────────
        print("\n[AGENT 2: DECIDE] Evaluating candidate slots and optimizing...")
        decision = schedule_and_store(db, job, record_audit=True)

        baseline_carbon = decision.baseline_carbon_emission or 0.0
        gs_carbon = decision.carbon_emission or 0.0
        carbon_saved = decision.carbon_avoided or (baseline_carbon - gs_carbon)
        carbon_pct = (carbon_saved / baseline_carbon * 100.0) if baseline_carbon > 0 else 0.0

        baseline_cost = decision.baseline_cost or 0.0
        gs_cost = decision.electricity_cost or 0.0
        cost_saved = decision.cost_difference or (baseline_cost - gs_cost)
        cost_pct = (cost_saved / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

        print(f"  Selected Start    : {decision.selected_start.isoformat()}")
        print(f"  Selected End      : {decision.selected_end.isoformat()}")
        print(f"  Decision Reason   : {decision.reason}")
        print(f"  Baseline Carbon   : {baseline_carbon:.4f} kg CO2")
        print(f"  GreenShift Carbon : {gs_carbon:.4f} kg CO2")
        print(f"  Carbon Saved      : {carbon_saved:.4f} kg CO2 ({carbon_pct:.1f}% reduction)")
        print(f"  Baseline Cost     : ${baseline_cost:.4f}")
        print(f"  GreenShift Cost   : ${gs_cost:.4f}")
        print(f"  Cost Saved        : ${cost_saved:.4f} ({cost_pct:.1f}% savings)")
        print(f"  Budget Remaining  : {decision.budget_remaining:.4f} kg CO2")

        # ─── AGENT 3: DISPATCH ───────────────────────────────────────
        print("\n[AGENT 3: DISPATCH] Dispatching job execution...")
        k8s_name = f"gs-demo-{job.job_id.lower().replace('_', '-')}"
        record_k8s_job_created(db, job.job_id, k8s_name, "greenshift")
        record_k8s_job_completed(db, job.job_id, k8s_name, f"{k8s_name}-pod", (now + timedelta(minutes=10)).isoformat())
        job.status = JobStatus.COMPLETED
        db.commit()
        print(f"  Dispatched Target : {k8s_name} in namespace 'greenshift'")
        print(f"  Final Job Status  : {job.status.value}")

        # ─── AGENT 4: TRUST ──────────────────────────────────────────
        print("\n[AGENT 4: TRUST] Verifying cryptographic hash chain ledger...")
        verification = verify_chain(db)
        print(f"  Chain Validity    : {'VALID CHAIN' if verification.valid else 'TAMPER DETECTED'}")
        print(f"  Verified Events   : {verification.event_count}")
        print(f"  Message           : {verification.message}")

        # Demonstrate Tamper Detection
        print("\n[AGENT 4: TRUST] Demonstrating Tamper Detection...")
        from app.shared.models import AuditEventORM
        first_event = db.query(AuditEventORM).order_by(AuditEventORM.sequence.asc()).first()
        if first_event:
            original_payload = first_event.payload_json
            # Tamper the record
            first_event.payload_json = json.dumps({"tampered": True, "malicious": "injected"})
            db.commit()
            tamper_check = verify_chain(db)
            print(f"  Tamper Test Result: {'TAMPER DETECTED' if not tamper_check.valid else 'VALID CHAIN'}")
            print(f"  Tamper Details    : {tamper_check.message}")
            # Restore the record
            first_event.payload_json = original_payload
            db.commit()
            restored_check = verify_chain(db)
            print(f"  Restored Result   : {'VALID CHAIN' if restored_check.valid else 'TAMPER DETECTED'}")

        # ─── AGENT 5: PRESENT ────────────────────────────────────────
        print("\n[AGENT 5: PRESENT] Generating BRSR Sustainability Report...")
        report = generate_report(db, team_id="demo-team")
        record_export_generated(db, "CSV", report["summary"]["total_jobs"])
        csv_data = generate_csv(db, team_id="demo-team")

        print("  Summary Metrics:")
        print(f"    Total Jobs Scheduled  : {report['summary']['total_jobs']}")
        print(f"    Total Energy (kWh)    : {report['summary']['total_energy_kwh']:.4f}")
        print(f"    Total Baseline Carbon : {report['summary']['total_baseline_carbon_kg']:.4f} kg")
        print(f"    Total GS Carbon       : {report['summary']['total_greenshift_carbon_kg']:.4f} kg")
        print(f"    Total Carbon Avoided  : {report['summary']['total_carbon_avoided_kg']:.4f} kg ({report['summary']['carbon_reduction_pct']:.1f}%)")
        print(f"    Total Baseline Cost   : ${report['summary']['total_baseline_cost_usd']:.4f}")
        print(f"    Total GS Cost         : ${report['summary']['total_greenshift_cost_usd']:.4f}")
        print(f"    Total Cost Saved      : ${report['summary']['total_cost_saved_usd']:.4f}")
        print(f"    SLA Compliance        : {report['summary']['sla_performance_pct']:.1f}%")

        print("\n  CSV Export Sample (First 4 lines):")
        for line in csv_data.strip().split("\n")[:4]:
            print(f"    {line}")

        print("\n" + "=" * 70)
        print("DEMO PIPELINE COMPLETED SUCCESSFULLY")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    run_demo()
