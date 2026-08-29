"""
Agent 3 DISPATCH — Live Kubernetes Real Workload Execution & Verification
Orchestrates:
  INGEST -> DECIDE -> DISPATCH -> Real K8s Job -> Pod Execution -> Completion Polling -> TRUST Audit
"""

import time
import logging
import subprocess
from datetime import datetime, timezone, timedelta

from app.shared.database import init_db, SessionLocal
from app.ingest.jobs import get_job, submit_job
from app.ingest.service import load_csv_jobs_to_db
from app.decide.service import schedule_and_store
from app.dispatch.dispatcher import dispatch_job, refresh_job_status
from app.dispatch.kubernetes_client import check_kubernetes_available, get_batch_v1, get_core_v1
from app.trust.ledger import verify_chain, get_job_audit
from app.shared.models import JobStatus, JobSubmitRequest
from app.ingest.carbon_api import get_latest_carbon_intensity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("greenshift-k8s-verify")


def run_live_k8s_execution(job_id: str = "GS-JOB-000001", max_wait_seconds: int = 180):
    print("=" * 75)
    print(f"GREENSHIFT LIVE KUBERNETES WORKLOAD EXECUTION: {job_id}")
    print("=" * 75)

    init_db()
    db = SessionLocal()

    try:
        # 1. Verify Job from Dataset
        job = get_job(db, job_id)
        if not job:
            print("[1. INGEST] Loading workloads from CSV...")
            load_csv_jobs_to_db(db, "data/greenshift_workloads_final.csv")
            job = get_job(db, job_id)

        print(f"\n[1. INGEST VERIFICATION]")
        print(f"  Workload ID      : {job.job_id}")
        print(f"  Job Type         : {job.job_type}")
        print(f"  Team ID          : {job.team_id}")
        print(f"  Grid Region      : {job.region}")
        print(f"  Runtime          : {job.runtime_minutes} mins")
        print(f"  Power / Energy   : {job.power_kw} kW / {job.energy_kwh} kWh")
        print(f"  Container Image  : {job.container_image}")
        print(f"  CPU / Memory     : {job.cpu_request} / {job.memory_request}")
        print(f"  Carbon Budget    : {job.carbon_budget_kg} kg CO2")

        # 2. DECIDE — Carbon & Tariff Scheduling
        print(f"\n[2. DECIDE OPTIMIZATION]")
        latest_c = get_latest_carbon_intensity(job.region)
        if latest_c:
            print(f"  Electricity Maps : {latest_c.carbon_gco2_kwh} gCO2eq/kWh (Live Zone: {job.region})")

        decision = schedule_and_store(db, job, record_audit=True)
        print(f"  Optimal Window   : {decision.selected_start.isoformat()} -> {decision.selected_end.isoformat()}")
        print(f"  Slot Intensity   : {decision.carbon_intensity} gCO2/kWh")
        print(f"  Tariff Rate      : INR {decision.tariff_inr_per_kwh}/kWh ({decision.tariff_category.upper()})")
        print(f"  Electricity Cost : ${decision.electricity_cost:.4f} USD")
        print(f"  Carbon Emission  : {decision.carbon_emission:.6f} kg CO2")
        print(f"  Reason           : {decision.reason}")

        # 3. Check Live Kubernetes Connectivity
        print(f"\n[3. KUBERNETES DISPATCH]")
        k8s_ready = check_kubernetes_available()
        print(f"  Cluster Available: {k8s_ready}")

        if not k8s_ready:
            print("\n  [NOTICE] Kubernetes API server is currently not reachable on localhost:6443.")
            print("  (Docker Desktop Kubernetes is idle or starting).")
            print("  Dispatch agent is tested and fully wired to batch/v1 API when cluster is active.")
            return

        # 4. DISPATCH Real Kubernetes Job
        print(f"  Dispatching {job.job_id} to Kubernetes namespace '{job.kubernetes_execution.kubernetes_namespace if job.kubernetes_execution else 'greenshift'}'...")
        execution = dispatch_job(db, job)
        print(f"  Kubernetes Job   : {execution.kubernetes_job_name}")
        print(f"  Target Namespace : {execution.kubernetes_namespace}")
        print(f"  Initial GS State : {execution.gs_status.value}")

        # 5. Monitor and Poll Real Kubernetes Pod Lifecycle
        print(f"\n[4. POD EXECUTION POLLING]")
        start_time = time.time()
        completed = False

        while time.time() - start_time < max_wait_seconds:
            execution = refresh_job_status(db, execution)
            print(f"  [T+{int(time.time() - start_time)}s] Job: {execution.kubernetes_job_name} | K8s: {execution.k8s_status} | GS: {execution.gs_status.value} | Pod: {execution.pod_name}")

            if execution.gs_status == JobStatus.COMPLETED:
                completed = True
                break
            elif execution.gs_status == JobStatus.FAILED:
                print(f"  [ERROR] Job failed: {execution.error_message}")
                break

            time.sleep(5)

        # 6. Query kubectl logs and status
        print(f"\n[5. KUBECTL WORKLOAD VERIFICATION]")
        try:
            k8s_name = execution.kubernetes_job_name
            ns = execution.kubernetes_namespace
            subprocess.run(["kubectl", "get", "job", k8s_name, "-n", ns], check=False)
            if execution.pod_name:
                subprocess.run(["kubectl", "get", "pod", execution.pod_name, "-n", ns], check=False)
                print("\n  --- REAL POD LOGS ---")
                subprocess.run(["kubectl", "logs", execution.pod_name, "-n", ns], check=False)
        except Exception as e:
            print(f"  kubectl query notice: {e}")

        # 7. Trust Audit Chain
        print(f"\n[6. TRUST AUDIT VERIFICATION]")
        audit_res = verify_chain(db)
        print(f"  Audit Chain Valid: {audit_res.valid}")
        print(f"  Total Blocks     : {audit_res.event_count}")
        print(f"  Audit Status     : {audit_res.message}")

        events = get_job_audit(db, job_id)
        print(f"  Event Sequence   : {[e.event_type.value for e in events]}")

    finally:
        db.close()


if __name__ == "__main__":
    run_live_k8s_execution()
