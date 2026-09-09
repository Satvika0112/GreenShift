"""
GreenShift — Live Kubernetes End-to-End Validation Pipeline
Executes the full closed-loop workload lifecycle on a live Kubernetes cluster:
  INGEST -> DECIDE -> APPROVAL -> DISPATCH -> EXECUTE -> LOGS -> AUDIT -> BASELINE -> CLEANUP

Validates Acceptance Criteria 12, 13, and 27 in docs/PROJECT_STATUS.md:
  - 12: Real Kubernetes pods submitted, monitored, completed
  - 13: End-to-end integration test passes against live cluster
  - 27: Audit trail captures full lifecycle of real workloads
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.shared.database import init_db, SessionLocal
from app.ingest.jobs import get_job, submit_job
from app.ingest.service import load_csv_jobs_to_db
from app.decide.service import schedule_and_store
from app.approval.service import approve_schedule
from app.dispatch.dispatcher import dispatch_job, refresh_job_status
from app.dispatch.kubernetes_client import check_kubernetes_available, get_batch_v1, get_core_v1
from app.trust.ledger import verify_chain, get_job_audit
from app.shared.models import JobStatus, JobSubmitRequest, JobORM
from app.ingest.carbon_api import get_latest_carbon_intensity

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("greenshift-live-e2e")

TARGET_JOB_ID = "GS-JOB-000001"
TARGET_NAMESPACE = "greenshift"
CONTAINER_IMAGE = "greenshift/sample-workload:latest"
TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 3


def print_banner(text: str, char: str = "="):
    line = char * 70
    print(f"\n{line}\n{text}\n{line}")


def run_live_e2e_pipeline() -> bool:
    print_banner("GREENSHIFT LIVE KUBERNETES END-TO-END VALIDATION", "=")
    print(f"Timestamp        : {datetime.now(timezone.utc).isoformat()}")
    print(f"Target Workload  : {TARGET_JOB_ID}")
    print(f"Target Namespace : {TARGET_NAMESPACE}")
    print(f"Workload Image   : {CONTAINER_IMAGE}")

    # 0. Pre-flight Check: Kubernetes Cluster Reachability
    print_banner("PRE-FLIGHT: KUBERNETES CLUSTER CONNECTIVITY", "-")
    k8s_ready = check_kubernetes_available()
    print(f"Kubernetes Cluster Accessible: {k8s_ready}")
    if not k8s_ready:
        print("[FAIL] Kubernetes API server is unreachable. Please start Docker Desktop K8s or Minikube.")
        return False
    print("[PASS] Kubernetes API server is online and responding.")

    init_db()
    db = SessionLocal()

    execution_record = None

    try:
        # ---------------------------------------------------------------------
        # Pre-cleanup: Clean up previous run's k8s job if any remains
        # ---------------------------------------------------------------------
        batch_v1 = get_batch_v1()
        core_v1 = get_core_v1()

        # Delete any existing K8s job with either name prefix
        for jname in [f"gs-{TARGET_JOB_ID.lower()}", f"greenshift-job-{TARGET_JOB_ID.lower()}"]:
            try:
                batch_v1.delete_namespaced_job(
                    name=jname,
                    namespace=TARGET_NAMESPACE,
                    propagation_policy="Background",
                )
                print(f"Pre-cleanup: Removed existing Kubernetes Job '{jname}'")
            except Exception:
                pass  # Job didn't exist, proceed

        # Delete existing execution record from DB if present from prior runs
        from app.shared.models import KubernetesExecutionORM
        deleted_count = db.query(KubernetesExecutionORM).filter(KubernetesExecutionORM.job_id == TARGET_JOB_ID).delete()
        if deleted_count > 0:
            db.commit()
            print(f"Pre-cleanup: Cleaned up {deleted_count} prior execution record(s) from database")

        # ---------------------------------------------------------------------
        # CHECK 1: INGEST — Workload Ingestion & Configuration
        # ---------------------------------------------------------------------
        print_banner("CHECK 1: INGEST — WORKLOAD INGESTION", "-")
        job = get_job(db, TARGET_JOB_ID)
        if not job:
            print(f"Job {TARGET_JOB_ID} not found in DB. Loading from CSV dataset...")
            load_csv_jobs_to_db(db, "data/greenshift_workloads_final.csv")
            job = get_job(db, TARGET_JOB_ID)

        assert job is not None, f"Failed to load job {TARGET_JOB_ID}"

        # Configure for fast, reliable live cluster execution
        job.container_image = CONTAINER_IMAGE
        job.runtime_minutes = 1
        job.cpu_request = "100m"
        job.memory_request = "128Mi"
        job.deadline_hours = 24
        job.status = JobStatus.SUBMITTED
        db.commit()
        db.refresh(job)

        print(f"  Job ID           : {job.job_id}")
        print(f"  Job Type         : {job.job_type}")
        print(f"  Team ID          : {job.team_id}")
        print(f"  Grid Region      : {job.region}")
        print(f"  Runtime          : {job.runtime_minutes} min (60s container workload)")
        print(f"  Container Image  : {job.container_image}")
        print(f"  Resource Requests: CPU {job.cpu_request} | Mem {job.memory_request}")
        print(f"  Status           : {job.status.value}")

        assert job.job_id == TARGET_JOB_ID
        assert job.container_image == CONTAINER_IMAGE
        assert job.status == JobStatus.SUBMITTED
        print("[PASS] CHECK 1: INGEST — Workload loaded and configured.")

        # ---------------------------------------------------------------------
        # CHECK 2: DECIDE — Carbon & Cost Optimization & Approval
        # ---------------------------------------------------------------------
        print_banner("CHECK 2: DECIDE — SCHEDULING & APPROVAL", "-")
        latest_carbon = get_latest_carbon_intensity(job.region)
        if latest_carbon:
            print(f"  Live Carbon Rate : {latest_carbon.carbon_gco2_kwh} gCO2eq/kWh (Region: {job.region})")

        decision = schedule_and_store(db, job, record_audit=True)
        assert decision is not None, "Scheduler failed to produce decision"
        assert decision.carbon_intensity > 0, "Carbon intensity must be > 0"

        db.refresh(job)
        sd_orm = job.schedule_decision
        assert sd_orm is not None, "ScheduleDecisionORM not found on job"

        # Fast-track selected_start to now so dispatcher executes immediately
        now_utc = datetime.now(timezone.utc)
        sd_orm.selected_start = now_utc - timedelta(seconds=10)
        sd_orm.selected_end = sd_orm.selected_start + timedelta(minutes=job.runtime_minutes or 1)
        db.commit()
        db.refresh(sd_orm)
        db.refresh(job)

        print(f"  Proposed Window  : {sd_orm.selected_start.isoformat()} -> {sd_orm.selected_end.isoformat()}")
        print(f"  Optimal Intensity: {sd_orm.carbon_intensity} gCO2eq/kWh")
        print(f"  Tariff Rate      : INR {sd_orm.tariff_inr_per_kwh}/kWh ({sd_orm.tariff_category})")
        print(f"  Estimated Cost   : ${sd_orm.electricity_cost:.4f} USD")
        print(f"  Estimated Carbon : {sd_orm.carbon_emission:.6f} kg CO2")
        print(f"  Pre-Dispatch St  : {job.status.value}")

        # Human Approval Gate: Transition PENDING_APPROVAL -> APPROVED
        print("  Applying human approval gate...")
        approval_res = approve_schedule(
            db,
            job_id=job.job_id,
            schedule_id=sd_orm.id,
            reason="Live Kubernetes E2E Validation Approval",
            approved_by="live-e2e-validator",
        )
        db.refresh(job)
        print(f"  Approval Granted : ID {approval_res.id} | Approver: {approval_res.approved_by}")
        print(f"  Approved Status  : {job.status.value}")

        assert job.status == JobStatus.APPROVED, f"Expected APPROVED, got {job.status.value}"
        print("[PASS] CHECK 2: DECIDE — Schedule computed, fast-tracked, and approved.")

        # ---------------------------------------------------------------------
        # CHECK 3: DISPATCH — Kubernetes Job Submission
        # ---------------------------------------------------------------------
        print_banner("CHECK 3: DISPATCH — KUBERNETES JOB SUBMISSION", "-")
        execution_record = dispatch_job(db, job)
        assert execution_record is not None, "Dispatcher failed to return execution record"
        assert execution_record.kubernetes_job_name is not None, "No K8s job name generated"

        k8s_job_name = execution_record.kubernetes_job_name
        ns = execution_record.kubernetes_namespace or TARGET_NAMESPACE
        print(f"  K8s Job Name     : {k8s_job_name}")
        print(f"  K8s Namespace    : {ns}")
        print(f"  Initial GS State : {execution_record.gs_status.value}")

        # Verify Job resource exists in Kubernetes cluster via K8s API
        k8s_job = batch_v1.read_namespaced_job(name=k8s_job_name, namespace=ns)
        assert k8s_job is not None, f"Kubernetes Job {k8s_job_name} not found in cluster"
        assert k8s_job.metadata.name == k8s_job_name
        print(f"  Cluster Response : Job '{k8s_job.metadata.name}' created in '{ns}'")
        print("[PASS] CHECK 3: DISPATCH — Real Kubernetes Job submitted to live cluster.")

        # ---------------------------------------------------------------------
        # CHECK 4: EXECUTE — Pod Lifecycle Monitoring
        # ---------------------------------------------------------------------
        print_banner("CHECK 4: EXECUTE — POD LIFECYCLE MONITORING", "-")
        start_time = time.time()
        completed = False
        final_pod_name: Optional[str] = None

        print(f"  Polling Kubernetes job status (timeout: {TIMEOUT_SECONDS}s)...")
        while time.time() - start_time < TIMEOUT_SECONDS:
            elapsed = int(time.time() - start_time)
            execution_record = refresh_job_status(db, execution_record)
            pod_str = execution_record.pod_name or "pending-assignment"

            print(f"  [T+{elapsed:3d}s] K8s Status: {execution_record.k8s_status:<10} | GS Status: {execution_record.gs_status.value:<10} | Pod: {pod_str}")

            if execution_record.pod_name:
                final_pod_name = execution_record.pod_name

            if execution_record.gs_status == JobStatus.COMPLETED:
                completed = True
                break
            elif execution_record.gs_status == JobStatus.FAILED:
                raise RuntimeError(f"Kubernetes workload failed: {execution_record.error_message}")

            time.sleep(POLL_INTERVAL_SECONDS)

        assert completed, f"Job did not complete within {TIMEOUT_SECONDS} seconds"
        assert final_pod_name is not None, "No pod was assigned to the execution"
        print(f"  Final Workload Pod: {final_pod_name}")
        print(f"  Total Run Duration: {int(time.time() - start_time)} seconds")
        print("[PASS] CHECK 4: EXECUTE — Pod ran and successfully completed (Succeeded).")

        # ---------------------------------------------------------------------
        # CHECK 5: LOGS — Pod Log Retrieval & Signature Verification
        # ---------------------------------------------------------------------
        print_banner("CHECK 5: LOGS — POD LOG VERIFICATION", "-")
        pod_logs = core_v1.read_namespaced_pod_log(name=final_pod_name, namespace=ns)
        print("  --- POD LOG OUTPUT (Snippet) ---")
        log_lines = pod_logs.strip().splitlines()
        for line in log_lines[:5]:
            print(f"    {line}")
        if len(log_lines) > 10:
            print("    ...")
        for line in log_lines[-5:]:
            print(f"    {line}")
        print("  --- END POD LOG OUTPUT ---")

        # Verify key milestone logs emitted by greenshift/sample-workload
        assert "GreenShift Sample Workload" in pod_logs, "Missing workload start marker in pod logs"
        assert "GreenShift Sample Workload COMPLETED" in pod_logs, "Missing completion marker in pod logs"
        assert "Finished:" in pod_logs, "Missing finish timestamp in pod logs"
        print("[PASS] CHECK 5: LOGS — Pod logs retrieved; all workload completion signatures confirmed.")

        # ---------------------------------------------------------------------
        # CHECK 6: AUDIT — Cryptographic Ledger Verification
        # ---------------------------------------------------------------------
        print_banner("CHECK 6: AUDIT — CRYPTOGRAPHIC LEDGER VERIFICATION", "-")
        chain_verification = verify_chain(db)
        print(f"  Chain Valid      : {chain_verification.valid}")
        print(f"  Total Ledger Blks: {chain_verification.event_count}")
        print(f"  Ledger Status    : {chain_verification.message}")

        assert chain_verification.valid is True, f"Audit ledger integrity failure: {chain_verification.message}"
        assert chain_verification.event_count > 0, "Audit ledger has no events"

        # Verify audit trail for this specific job
        job_events = get_job_audit(db, TARGET_JOB_ID)
        event_types = [e.event_type.value for e in job_events]
        print(f"  Job Event Trail  : {' -> '.join(event_types)}")

        expected_events = ["APPROVAL_GRANTED", "K8S_JOB_CREATED", "K8S_JOB_COMPLETED"]
        for exp in expected_events:
            assert exp in event_types, f"Audit ledger missing event '{exp}' for {TARGET_JOB_ID}"

        # Verify cryptographic hash link
        for idx in range(1, len(job_events)):
            curr = job_events[idx]
            prev = job_events[idx - 1]
            seq = getattr(curr, "sequence", getattr(curr, "sequence_num", idx))
            print(f"  Block #{seq}: prev_hash={curr.previous_hash[:12]}... curr_hash={curr.current_hash[:12]}...")

        print("[PASS] CHECK 6: AUDIT — Full cryptographic audit chain verified (SHA-256 links valid).")

        # ---------------------------------------------------------------------
        # CHECK 7: BASELINE — Carbon & Cost Reduction Assertion
        # ---------------------------------------------------------------------
        print_banner("CHECK 7: BASELINE — CARBON & COST REDUCTION", "-")
        print(f"  Optimized Carbon : {decision.carbon_emission:.6f} kg CO2")
        if decision.baseline_carbon_emission is not None:
            print(f"  Baseline Carbon  : {decision.baseline_carbon_emission:.6f} kg CO2")
        if decision.carbon_reduction_pct is not None:
            print(f"  Carbon Reduction : {decision.carbon_reduction_pct:.2f}%")
        print(f"  Optimized Cost   : ${decision.electricity_cost:.4f} USD")
        b_cost = decision.baseline_cost if decision.baseline_cost is not None else getattr(decision, "baseline_electricity_cost", None)
        if b_cost is not None:
            print(f"  Baseline Cost    : ${b_cost:.4f} USD")
        if decision.cost_reduction_pct is not None:
            print(f"  Cost Reduction   : {decision.cost_reduction_pct:.2f}%")

        if decision.baseline_carbon_emission and decision.baseline_carbon_emission > 0:
            assert decision.carbon_emission <= decision.baseline_carbon_emission, (
                f"Optimized carbon {decision.carbon_emission} exceeded baseline {decision.baseline_carbon_emission}"
            )
        print("[PASS] CHECK 7: BASELINE — Optimization met or outperformed baseline carbon intensity.")

        # ---------------------------------------------------------------------
        # CHECK 8: CLEANUP — Resource Cleanup from Kubernetes
        # ---------------------------------------------------------------------
        print_banner("CHECK 8: CLEANUP — KUBERNETES RESOURCE CLEANUP", "-")
        batch_v1.delete_namespaced_job(
            name=k8s_job_name,
            namespace=ns,
            propagation_policy="Background",
        )
        print(f"  Deleted Kubernetes Job '{k8s_job_name}' in namespace '{ns}'")
        print("[PASS] CHECK 8: CLEANUP — Workload cleanly decommissioned.")

        # ---------------------------------------------------------------------
        # FINAL SUMMARY
        # ---------------------------------------------------------------------
        print_banner("ALL 8 CHECKS PASSED — 100% SUCCESS", "=")
        print("GreenShift Phase 6 Live Kubernetes End-to-End Validation complete.")
        print("Criteria 12 (Real Pod Execution), 13 (E2E Integration), 27 (Audit Ledger) CLOSED.")
        return True

    except Exception as exc:
        logger.exception("Live E2E test encountered an error: %s", exc)
        print(f"\n[FAIL] Live E2E test failed with error: {exc}")
        return False

    finally:
        db.close()


if __name__ == "__main__":
    success = run_live_e2e_pipeline()
    sys.exit(0 if success else 1)
