# GreenShift — Error Log

This document records integration errors, known bugs, and workarounds discovered during development.
Every agent must update this when they encounter or resolve a significant error.

---

## Format

```
## ERROR-XXX: Short title
Date: YYYY-MM-DD
Agent: Agent N
Status: OPEN | RESOLVED
Description: What happened.
Root cause: Why it happened.
Resolution: What fixed it.
```

## ERROR-001: Missing greenshift-db-secrets in Kubernetes Manifests
Date: 2026-09-08  
Agent: Agent 6 (Kubernetes Validation)  
Status: RESOLVED  
Description: Postgres pod failed to mount password from `greenshift-db-secrets`.  
Root cause: `k8s/secrets.yaml` did not include the `greenshift-db-secrets` resource definition.  
Resolution: Added `greenshift-db-secrets` Secret containing base64-encoded `POSTGRES_PASSWORD` (`greenshift`) to `k8s/secrets.yaml`.

---

## ERROR-002: API Deployment Probe 404 Failure
Date: 2026-09-08  
Agent: Agent 6 (Kubernetes Validation)  
Status: RESOLVED  
Description: `greenshift-api` container restarted repeatedly due to startup probe failure.  
Root cause: Deployment manifest queried `/healthz`, whereas the FastAPI application exposes `/health`.  
Resolution: Updated `k8s/deployments.yaml` liveness, readiness, and startup probes for `greenshift-api` to target `/health`.

---

## ERROR-003: Pod Tracker Selecting Stale/Terminating Pods
Date: 2026-09-08  
Agent: Agent 6 (Kubernetes Validation)  
Status: RESOLVED  
Description: `read_namespaced_pod_log` threw 404 Not Found when attempting to fetch logs for a re-run workload.  
Root cause: `status_tracker.py` picked the first pod returned by `list_namespaced_pod`, which included pods in `Terminating` state (`deletion_timestamp is not None`).  
Resolution: Updated `get_pod_name` in `app/dispatch/status_tracker.py` to filter out pods with active `deletion_timestamp` and sort remaining pods by `creation_timestamp` descending.

---

## ERROR-004: Approval Gate Requirement for Workload Dispatch
Date: 2026-09-08  
Agent: Agent 6 (Kubernetes Validation)  
Status: RESOLVED  
Description: Calling `dispatch_job` on a newly scheduled job raised `DispatchError: Job must be in status APPROVED or QUEUED`.  
Root cause: GreenShift's safety design requires human approval before Kubernetes job dispatch.  
Resolution: Integrated `approve_schedule()` step after `schedule_and_store()` in test and execution harnesses.

---

## ERROR-005: Job Schedule Decision Time Window Constraint
Date: 2026-09-08  
Agent: Agent 6 (Kubernetes Validation)  
Status: RESOLVED  
Description: Updating `selected_start` to current time caused database check constraint violation `ck_schedule_decisions_time_window`.  
Root cause: The database table enforces `selected_end > selected_start`. Setting `selected_start` without adjusting `selected_end` violated this constraint.  
Resolution: When fast-tracking jobs for immediate testing, updated both `selected_start` and set `selected_end = selected_start + timedelta(minutes=job.runtime_minutes or 1)`.
