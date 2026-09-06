# GreenShift End-to-End Demonstration Guide

This guide walks through the end-to-end execution of the GreenShift carbon-aware scheduling pipeline.

---

## 1. Quick Automated Demo

Run the automated demonstration script:
```bash
python scripts/demo_pipeline.py
```

Expected output highlights:
```text
======================================================================
GREENSHIFT END-TO-END SYSTEM DEMONSTRATION
======================================================================

[DATA SOURCES ACTIVE]
  Carbon Intensity : LIVE API (Electricity Maps live API)
  Electricity Tariff: Master Regional Tariff Dataset (data/master_tod_tariff_all_regions.csv)

[AGENT 1: INGEST] Submitting and validating job...
  Registered Job ID : JOB-44BB6EC3
  Team              : demo-team
  Runtime           : 10 mins
  Power             : 5.0 kW
  Region            : IN-WE
  Deadline          : 2026-08-19T03:24:43.894985
  Status            : SUBMITTED

[AGENT 2: DECIDE] Evaluating candidate slots and optimizing...
  Selected Start    : 2026-08-19T03:00:00+00:00
  Selected End      : 2026-08-19T03:10:00+00:00
  Decision Reason   : Lowest carbon window within deadline and budget
  Baseline Carbon   : 0.5442 kg CO2
  GreenShift Carbon : 0.4750 kg CO2
  Carbon Saved      : 0.0692 kg CO2 (12.7% reduction)
  Baseline Cost     : $0.0915
  GreenShift Cost   : $0.1098
  Budget Remaining  : 1.5250 kg CO2

[AGENT 3: DISPATCH] Dispatching job execution...
  Dispatched Target : gs-demo-job-44bb6ec3 in namespace 'greenshift'
  Final Job Status  : COMPLETED

[AGENT 4: TRUST] Verifying cryptographic hash chain ledger...
  Chain Validity    : VALID CHAIN
  Verified Events   : 9
  Message           : Audit chain is intact (9 records verified)

[AGENT 4: TRUST] Demonstrating Tamper Detection...
  Tamper Test Result: TAMPER DETECTED
  Tamper Details    : Sequence 1: payload_hash mismatch (data tampered)
  Restored Result   : VALID CHAIN

[AGENT 5: PRESENT] Generating BRSR Sustainability Report...
  Summary Metrics:
    Total Jobs Scheduled  : 2
    Total Energy (kWh)    : 1.6667
    Total Baseline Carbon : 1.0883 kg
    Total GS Carbon       : 0.9500 kg
    Total Carbon Avoided  : 0.1383 kg (12.7%)
    SLA Compliance        : 100.0%
```

---

## 2. Interactive REST API Demo

### Step 1: Submit Workload
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "team_id": "demo-team",
    "deadline": "2026-08-19T18:00:00Z",
    "runtime_minutes": 10,
    "power_kw": 5.0,
    "region": "IN-WE",
    "container_image": "greenshift/sample-workload:latest",
    "carbon_budget_kg": 2.0
  }'
```

### Step 2: Trigger Scheduling (Enters PENDING_APPROVAL)
```bash
curl -X POST http://localhost:8000/api/v1/schedule/{JOB_ID}
```
*The job enters `PENDING_APPROVAL` status and is held until explicitly approved.*

### Step 3: Approve Proposed Schedule (Human Approval Gate)
```bash
curl -X POST http://localhost:8000/api/v1/approvals/{JOB_ID}/approve \
  -H "Content-Type: application/json" \
  -d '{
    "schedule_id": 1,
    "reason": "Off-peak low-carbon window approved"
  }'
```
*Transitions status to `APPROVED`. If declined via `/decline`, the job stops and is never dispatched.*

### Step 4: Trigger Dispatch (Authorized only for APPROVED jobs)
```bash
curl -X POST http://localhost:8000/api/v1/dispatch/{JOB_ID}
```

### Step 5: Verify Audit Chain
```bash
curl http://localhost:8000/api/v1/trust/verify
```

### Step 6: Export BRSR Report
```bash
curl http://localhost:8000/api/v1/report/csv -o report.csv
```
