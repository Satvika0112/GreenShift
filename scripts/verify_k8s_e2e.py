"""
End-to-End Live Kubernetes Integration Verification Script.
Tests:
1. Job Submission
2. Scheduling Decision
3. Dynamic Kubernetes Job Creation
4. Pod execution & log capture
5. GreenShift & K8s status tracking (SCHEDULED -> QUEUED -> RUNNING -> COMPLETED)
6. Trust Ledger recording
"""

import time
import logging
from datetime import datetime, timedelta, timezone

from app.shared.database import SessionLocal, init_db
from app.shared.models import JobSubmitRequest, JobStatus, JobORM, KubernetesExecutionORM, AuditEventORM
from app.ingest.jobs import submit_job
from app.decide.service import schedule_and_store
from app.dispatch.dispatcher import dispatch_job, refresh_job_status
from app.dispatch.kubernetes_client import check_kubernetes_available, get_batch_v1, get_core_v1

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("e2e-verifier")


def main():
    logger.info("=== STEP 1: Verifying Kubernetes Cluster Reachability ===")
    assert check_kubernetes_available(), "Kubernetes API must be reachable!"
    logger.info("Kubernetes API is REACHABLE and READY.")

    init_db()
    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc)
        logger.info("=== STEP 2: Submitting Test Workload ===")
        req = JobSubmitRequest(
            team_id="E2E-VERIFICATION",
            deadline=now + timedelta(hours=2),
            runtime_minutes=1,
            power_kw=0.5,
            region="IN-SO",
            container_image="greenshift/sample-workload:latest",
            cpu_request="100m",
            memory_request="64Mi",
        )
        job = submit_job(db, req)
        logger.info("Job submitted: %s (status: %s)", job.job_id, job.status)
        assert job.status == JobStatus.SUBMITTED

        logger.info("=== STEP 3: Scheduling Job ===")
        decision = schedule_and_store(db, job)
        db.refresh(job)
        # Ensure selected_start is set to now so dispatcher picks it up immediately
        decision.selected_start = now - timedelta(seconds=10)
        db.commit()
        db.refresh(job)
        logger.info("Job scheduled: %s (status: %s, selected_start: %s)", job.job_id, job.status, decision.selected_start)
        assert job.status == JobStatus.SCHEDULED

        logger.info("=== STEP 4: Dispatching to Kubernetes ===")
        execution = dispatch_job(db, job)
        db.refresh(job)
        logger.info(
            "Dispatched Job: %s -> K8s Job: %s (namespace: %s, status: %s)",
            job.job_id,
            execution.kubernetes_job_name,
            execution.kubernetes_namespace,
            job.status,
        )
        assert job.status == JobStatus.QUEUED

        logger.info("=== STEP 5: Verifying Kubernetes Job in Cluster ===")
        batch = get_batch_v1()
        k8s_job = batch.read_namespaced_job(
            name=execution.kubernetes_job_name,
            namespace=execution.kubernetes_namespace,
        )
        assert k8s_job is not None
        assert k8s_job.metadata.labels.get("app") == "greenshift"
        assert k8s_job.metadata.labels.get("greenshift-job-id") == job.job_id
        logger.info("Kubernetes Job found with correct metadata & labels.")

        logger.info("=== STEP 6: Tracking Pod Lifecycle & Waiting for Completion ===")
        core = get_core_v1()
        max_wait = 90
        start_wait = time.time()
        pod_name = None

        while time.time() - start_wait < max_wait:
            execution = refresh_job_status(db, execution)
            db.refresh(job)
            logger.info("Current status -> K8s: %s | GreenShift: %s | Pod: %s", execution.k8s_status, execution.gs_status, execution.pod_name)

            if execution.pod_name and not pod_name:
                pod_name = execution.pod_name
                logger.info("Discovered Pod name: %s", pod_name)

            if execution.gs_status == JobStatus.COMPLETED:
                logger.info("Job execution reached COMPLETED status!")
                break

            time.sleep(3)

        assert execution.gs_status == JobStatus.COMPLETED, f"Job did not complete in time, status: {execution.gs_status}"

        logger.info("=== STEP 7: Fetching Workload Pod Logs ===")
        if pod_name:
            pod_logs = core.read_namespaced_pod_log(name=pod_name, namespace=execution.kubernetes_namespace)
            logger.info("Pod Logs Output:\n%s", pod_logs)
            assert "GreenShift Sample Workload Starting" in pod_logs
            assert "GreenShift Sample Workload COMPLETED" in pod_logs

        logger.info("=== STEP 8: Verifying Trust Audit Ledger ===")
        audit_events = (
            db.query(AuditEventORM)
            .filter(AuditEventORM.job_id == job.job_id)
            .order_by(AuditEventORM.sequence.asc())
            .all()
        )
        event_types = [e.event_type for e in audit_events]
        logger.info("Recorded Audit Events for %s: %s", job.job_id, event_types)
        assert any("CREATED" in e or "SUBMITTED" in e for e in event_types), "Must have creation event"
        assert any("STARTED" in e or "CREATED" in e for e in event_types), "Must have lifecycle events"

        from app.trust.ledger import verify_chain
        res = verify_chain(db)
        logger.info("Trust Audit Chain Verification: Valid = %s, Total Records = %d, Message = %s", res.valid, res.event_count, res.message)
        assert res.valid, f"Audit chain must be cryptographically valid! Details: {res}"

        logger.info("=== ALL END-TO-END VERIFICATION CHECKS PASSED SUCCESSFULLY! ===")

    finally:
        db.close()


if __name__ == "__main__":
    main()
